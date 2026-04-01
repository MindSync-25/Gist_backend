from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.avatar_signing import build_avatar_display_url
from app.core.comment_moderation import moderate_comment_text
from app.core.config import get_settings
from app.core.database import get_db
from app.core.notifications import create_notification
from app.models.comic import Comic
from app.models.comic_comment import ComicComment
from app.models.comic_comment_reaction import ComicCommentReaction
from app.models.comic_metric import ComicMetric
from app.models.comic_reaction import ComicReaction
from app.models.topic import Topic
from app.models.user import User
from app.schemas.comment import CommentCreateIn, CommentDeleteOut, CommentOut, CommentReactionIn, CommentReactionOut
from app.schemas.comic import ComicOut
from app.schemas.post import PostReactionIn, PostReactionOut

router = APIRouter(prefix="/comics", tags=["comics"])
SUPPORTED_COMIC_LANGUAGES = {"en", "hi", "kn", "ta", "te"}


@lru_cache
def _s3_client():
    import boto3

    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.Session(**kwargs).client("s3", region_name=settings.aws_region)


def _fresh_url(s3_key: str | None) -> str | None:
    """Generate a fresh presigned GET URL from the stable s3_key."""
    if not s3_key:
        return None
    try:
        settings = get_settings()
        return _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_name, "Key": s3_key},
            ExpiresIn=settings.s3_content_presign_expiry_seconds,
        )
    except Exception:
        return None


def _ensure_comic_exists(db: Session, comic_id: int) -> Comic:
    comic = db.get(Comic, comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")
    return comic


def _get_or_create_metrics(db: Session, comic_id: int) -> ComicMetric:
    metric = db.get(ComicMetric, comic_id)
    if metric is None:
        metric = ComicMetric(comic_id=comic_id)
        db.add(metric)
        db.flush()
    return metric


def _normalize_language_code(language: str | None) -> str:
    if not language:
        return "en"
    code = str(language).strip().lower().split("-")[0]
    return code if code in SUPPORTED_COMIC_LANGUAGES else "en"


def _safe_localized_copy(raw: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}

    out: dict[str, dict[str, str]] = {}
    for lang in SUPPORTED_COMIC_LANGUAGES:
        val = raw.get(lang)
        if not isinstance(val, dict):
            continue
        out[lang] = {
            "banner_title": str(val.get("banner_title", "")).strip(),
            "summary": str(val.get("summary", "")).strip(),
        }
    return out


def _localized_field(
    localized_copy: dict[str, dict[str, str]],
    language: str,
    field: str,
    fallback: str | None,
) -> str | None:
    fallback_text = (fallback or "").strip() or None
    lang_val = (localized_copy.get(language, {}) or {}).get(field, "").strip()
    if lang_val:
        return lang_val
    en_val = (localized_copy.get("en", {}) or {}).get(field, "").strip()
    if en_val:
        return en_val
    return fallback_text


def _map_comment_out(comic_id: int, comment: ComicComment, users_by_id: dict[int, User], liked_by_viewer: bool = False) -> CommentOut:
    author = users_by_id.get(comment.user_id) if comment.user_id is not None else None
    author_avatar_display_url = None
    author_avatar_display_expires_at = None
    if author is not None:
        author_avatar_display_url, author_avatar_display_expires_at = build_avatar_display_url(author.avatar_url)

    return CommentOut(
        id=comment.id,
        post_id=comic_id,
        user_id=comment.user_id,
        author_username=author.username if author else None,
        author_display_name=author.display_name if author else None,
        author_avatar_url=author.avatar_url if author else None,
        author_avatar_display_url=author_avatar_display_url,
        author_avatar_display_expires_at=author_avatar_display_expires_at,
        parent_comment_id=comment.parent_comment_id,
        body=comment.body,
        status=comment.status,
        reactions_count=comment.reactions_count,
        liked_by_viewer=liked_by_viewer,
        replies_count=comment.replies_count,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


def _category_tokens_for_topic_slug(slug: str) -> set[str]:
    base = slug.strip().lower()
    if not base:
        return set()

    alias_map: dict[str, set[str]] = {
        "politics": {"politics", "political"},
        "sports": {"sports", "sport"},
        "business": {"business", "economy", "economic"},
        "tech": {"tech", "technology"},
        "entertainment": {"entertainment", "movies", "movie", "culture"},
        "finance": {"finance", "financial", "markets", "market"},
    }
    return alias_map.get(base, {base})


def _viewer_preferred_comic_categories(db: Session, viewer_user_id: int | None) -> set[str]:
    if viewer_user_id is None:
        return set()

    viewer = db.get(User, viewer_user_id)
    if viewer is None:
        return set()

    topic_slugs = list(dict.fromkeys(viewer.preferred_topic_slugs or []))
    if not topic_slugs:
        return set()

    active_topic_slugs = db.execute(
        select(Topic.slug).where(
            Topic.slug.in_(topic_slugs),
            Topic.is_active.is_(True),
        )
    ).scalars().all()

    categories: set[str] = set()
    for slug in active_topic_slugs:
        categories.update(_category_tokens_for_topic_slug(slug))
    return categories


@router.get("", response_model=list[ComicOut])
def list_comics(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    language: str = Query(default="en"),
    viewer_user_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> list[ComicOut]:
    active_language = _normalize_language_code(language)
    base_stmt = select(Comic).where(func.coalesce(Comic.s3_key, "") != "")

    preferred_categories = _viewer_preferred_comic_categories(db, viewer_user_id)
    if not preferred_categories:
        rows = list(
            db.execute(
                base_stmt.order_by(desc(Comic.generated_at), desc(Comic.id)).limit(limit).offset(offset)
            ).scalars().all()
        )
    else:
        # Blend: ~75% preferred categories + ~25% discovery (other categories)
        need = limit + offset
        interest_stmt = base_stmt.where(
            func.lower(func.coalesce(Comic.category, "")).in_(preferred_categories)
        )
        interest_comics = list(
            db.execute(
                interest_stmt.order_by(desc(Comic.generated_at), desc(Comic.id)).limit(need * 2)
            ).scalars().all()
        )
        interest_ids = {c.id for c in interest_comics}

        discovery_stmt = base_stmt.where(
            func.lower(func.coalesce(Comic.category, "")).notin_(preferred_categories)
        )
        if interest_ids:
            discovery_stmt = discovery_stmt.where(Comic.id.notin_(list(interest_ids)))
        discovery_size = max(need // 4, 3)
        discovery_comics = list(
            db.execute(
                discovery_stmt.order_by(desc(Comic.generated_at), desc(Comic.id)).limit(discovery_size * 2)
            ).scalars().all()
        )

        # Interleave: pattern [I, I, I, D] → 75% interest, 25% discovery
        merged: list = []
        ii = di = 0
        pattern = ['I', 'I', 'I', 'D']
        while len(merged) < need:
            added = 0
            for slot in pattern:
                if len(merged) >= need:
                    break
                if slot == 'I':
                    if ii < len(interest_comics):
                        merged.append(interest_comics[ii]); ii += 1; added += 1
                    elif di < len(discovery_comics):
                        merged.append(discovery_comics[di]); di += 1; added += 1
                elif slot == 'D':
                    if di < len(discovery_comics):
                        merged.append(discovery_comics[di]); di += 1; added += 1
                    elif ii < len(interest_comics):
                        merged.append(interest_comics[ii]); ii += 1; added += 1
            if added == 0:
                break
        rows = merged[offset:offset + limit]

    comic_ids = [comic.id for comic in rows]
    metrics = db.execute(select(ComicMetric).where(ComicMetric.comic_id.in_(comic_ids))).scalars().all() if comic_ids else []
    metric_by_comic_id = {metric.comic_id: metric for metric in metrics}

    liked_comic_ids: set[int] = set()
    if viewer_user_id is not None and comic_ids:
        liked_comic_ids = set(
            db.execute(
                select(ComicReaction.comic_id).where(
                    ComicReaction.comic_id.in_(comic_ids),
                    ComicReaction.user_id == viewer_user_id,
                    ComicReaction.reaction_type == "like",
                )
            ).scalars().all()
        )

    result: list[ComicOut] = []
    for comic in rows:
        metric = metric_by_comic_id.get(comic.id)
        localized_copy = _safe_localized_copy(comic.localized_copy)
        localized_banner = _localized_field(localized_copy, active_language, "banner_title", comic.banner_title)
        localized_summary = _localized_field(localized_copy, active_language, "summary", comic.summary)
        result.append(
            ComicOut(
                id=comic.id,
                linked_post_id=None,
                article_url=comic.article_url,
                headline=comic.headline,
                category=comic.category,
                run_date=comic.run_date,
                tone=comic.tone,
                summary=localized_summary,
                banner_title=localized_banner,
                scene=comic.scene,
                hero_character=comic.hero_character,
                background=comic.background,
                dialogue=comic.dialogue,
                image_prompt=comic.image_prompt,
                localized_copy=localized_copy or None,
                s3_key=comic.s3_key,
                s3_url=_fresh_url(comic.s3_key) or comic.s3_url,
                generated_at=comic.generated_at,
                likes_count=metric.likes_count if metric else 0,
                comments_count=metric.comments_count if metric else 0,
                shares_count=metric.shares_count if metric else 0,
                liked_by_viewer=comic.id in liked_comic_ids,
            )
        )
    return result


@router.get("/{comic_id}/comments", response_model=list[CommentOut])
def list_comic_comments(
    comic_id: int,
    viewer_user_id: int | None = Query(default=None, ge=1),
    parent_comment_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[CommentOut]:
    _ensure_comic_exists(db, comic_id)

    stmt = (
        select(ComicComment)
        .where(
            ComicComment.comic_id == comic_id,
            ComicComment.status == "published",
        )
        .order_by(ComicComment.created_at.asc(), ComicComment.id.asc())
        .limit(limit)
        .offset(offset)
    )

    if parent_comment_id is not None:
        stmt = stmt.where(ComicComment.parent_comment_id == parent_comment_id)

    comments = db.execute(stmt).scalars().all()
    if not comments:
        return []

    user_ids = {comment.user_id for comment in comments if comment.user_id is not None}
    users_by_id: dict[int, User] = {}
    if user_ids:
        users = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
        users_by_id = {user.id: user for user in users}

    liked_comment_ids: set[int] = set()
    if viewer_user_id is not None:
        comment_ids = [comment.id for comment in comments]
        liked_comment_ids = set(
            db.execute(
                select(ComicCommentReaction.comment_id).where(
                    ComicCommentReaction.comment_id.in_(comment_ids),
                    ComicCommentReaction.user_id == viewer_user_id,
                    ComicCommentReaction.reaction_type == "like",
                )
            ).scalars().all()
        )

    return [_map_comment_out(comic_id, comment, users_by_id, comment.id in liked_comment_ids) for comment in comments]


@router.post("/{comic_id}/comments", response_model=CommentOut)
def create_comic_comment(
    comic_id: int,
    payload: CommentCreateIn,
    db: Session = Depends(get_db),
) -> CommentOut:
    _ensure_comic_exists(db, comic_id)
    moderation = moderate_comment_text(payload.body)
    if not moderation.allowed:
        raise HTTPException(status_code=422, detail=moderation.reason or "Comment violates moderation guidelines.")

    if payload.parent_comment_id is not None:
        parent = db.get(ComicComment, payload.parent_comment_id)
        if parent is None or parent.comic_id != comic_id:
            raise HTTPException(status_code=400, detail="Invalid parent_comment_id")
    else:
        parent = None

    comment = ComicComment(
        comic_id=comic_id,
        user_id=payload.user_id,
        parent_comment_id=payload.parent_comment_id,
        body=payload.body.strip(),
        status="published",
    )
    db.add(comment)

    metrics = _get_or_create_metrics(db, comic_id)
    metrics.comments_count += 1
    metrics.updated_at = datetime.now(timezone.utc)

    if parent is not None:
        parent.replies_count += 1
        parent.updated_at = datetime.now(timezone.utc)

    db.flush()

    try:
        if parent is not None and parent.user_id is not None and int(parent.user_id) != int(payload.user_id):
            create_notification(
                db,
                recipient_user_id=int(parent.user_id),
                actor_user_id=int(payload.user_id),
                notification_type="comment_reply",
                entity_type="comic_comment",
                entity_id=int(parent.id),
                payload={
                    "kind": "comic_comment_reply",
                    "comic_id": int(comic_id),
                    "parent_comment_id": int(parent.id),
                    "comment_id": int(comment.id),
                },
            )
    except Exception:
        pass

    db.commit()
    db.refresh(comment)
    author = db.get(User, payload.user_id)
    users_by_id = {author.id: author} if author is not None else {}
    return _map_comment_out(comic_id, comment, users_by_id, liked_by_viewer=False)


@router.post("/{comic_id}/comments/{comment_id}/reactions", response_model=CommentReactionOut)
def react_to_comic_comment(
    comic_id: int,
    comment_id: int,
    payload: CommentReactionIn,
    db: Session = Depends(get_db),
) -> CommentReactionOut:
    _ensure_comic_exists(db, comic_id)

    comment = db.get(ComicComment, comment_id)
    if comment is None or comment.comic_id != comic_id or comment.status == "deleted":
        raise HTTPException(status_code=404, detail="Comment not found")

    existing = db.execute(
        select(ComicCommentReaction).where(
            ComicCommentReaction.comment_id == comment_id,
            ComicCommentReaction.user_id == payload.user_id,
        )
    ).scalar_one_or_none()

    liked = True
    if existing is None:
        db.add(
            ComicCommentReaction(
                comment_id=comment_id,
                user_id=payload.user_id,
                reaction_type=payload.reaction_type,
            )
        )
        comment.reactions_count += 1
        try:
            if comment.user_id is not None and int(comment.user_id) != int(payload.user_id):
                create_notification(
                    db,
                    recipient_user_id=int(comment.user_id),
                    actor_user_id=int(payload.user_id),
                    notification_type="post_reaction",
                    entity_type="comic_comment",
                    entity_id=int(comment_id),
                    payload={
                        "kind": "comic_comment_reaction",
                        "comic_id": int(comic_id),
                        "comment_id": int(comment_id),
                        "reaction_type": payload.reaction_type,
                    },
                )
        except Exception:
            pass
    elif existing.reaction_type == payload.reaction_type:
        db.delete(existing)
        comment.reactions_count = max(0, comment.reactions_count - 1)
        liked = False
    else:
        existing.reaction_type = payload.reaction_type

    comment.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(comment)

    return CommentReactionOut(
        ok=True,
        post_id=comic_id,
        comment_id=comment_id,
        reaction_type=payload.reaction_type,
        reactions_count=comment.reactions_count,
        liked=liked,
    )


@router.delete("/{comic_id}/comments/{comment_id}", response_model=CommentDeleteOut)
def delete_comic_comment(
    comic_id: int,
    comment_id: int,
    user_id: int = Query(gt=0),
    db: Session = Depends(get_db),
) -> CommentDeleteOut:
    _ensure_comic_exists(db, comic_id)

    comment = db.get(ComicComment, comment_id)
    if comment is None or comment.comic_id != comic_id:
        raise HTTPException(status_code=404, detail="Comment not found")

    if comment.user_id != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own comment")

    comments_to_delete = [comment]
    direct_replies = db.execute(
        select(ComicComment).where(
            ComicComment.comic_id == comic_id,
            ComicComment.parent_comment_id == comment.id,
            ComicComment.status != "deleted",
        )
    ).scalars().all()
    comments_to_delete.extend(direct_replies)

    deleted_count = 0
    for item in comments_to_delete:
        if item.status == "deleted":
            continue
        item.status = "deleted"
        item.updated_at = datetime.now(timezone.utc)
        deleted_count += 1

    if comment.parent_comment_id is not None:
        parent = db.get(ComicComment, comment.parent_comment_id)
        if parent is not None:
            parent.replies_count = max(0, parent.replies_count - 1)
            parent.updated_at = datetime.now(timezone.utc)

    if deleted_count > 0:
        metrics = _get_or_create_metrics(db, comic_id)
        metrics.comments_count = max(0, metrics.comments_count - deleted_count)
        metrics.updated_at = datetime.now(timezone.utc)

    db.commit()

    return CommentDeleteOut(
        ok=True,
        post_id=comic_id,
        comment_id=comment_id,
        deleted_count=deleted_count,
    )


@router.post("/{comic_id}/reactions", response_model=PostReactionOut)
def react_to_comic(
    comic_id: int,
    payload: PostReactionIn,
    db: Session = Depends(get_db),
) -> PostReactionOut:
    _ensure_comic_exists(db, comic_id)

    existing = db.execute(
        select(ComicReaction).where(
            ComicReaction.comic_id == comic_id,
            ComicReaction.user_id == payload.user_id,
        )
    ).scalar_one_or_none()

    metrics = _get_or_create_metrics(db, comic_id)
    liked = True

    if existing is None:
        db.add(
            ComicReaction(
                comic_id=comic_id,
                user_id=payload.user_id,
                reaction_type=payload.reaction_type,
            )
        )
        metrics.likes_count += 1
    elif existing.reaction_type == payload.reaction_type:
        db.delete(existing)
        metrics.likes_count = max(0, metrics.likes_count - 1)
        liked = False
    else:
        existing.reaction_type = payload.reaction_type

    metrics.updated_at = datetime.now(timezone.utc)
    db.commit()

    return PostReactionOut(
        ok=True,
        post_id=comic_id,
        reaction_type=payload.reaction_type,
        likes_count=metrics.likes_count,
        liked=liked,
    )
