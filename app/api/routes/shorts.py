from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.avatar_signing import build_avatar_display_url
from app.core.comment_moderation import moderate_comment_text
from app.core.database import get_db
from app.core.notifications import create_notification
from app.models.short import Short
from app.models.short_bookmark import ShortBookmark
from app.models.short_comment import ShortComment
from app.models.short_comment_reaction import ShortCommentReaction
from app.models.short_metric import ShortMetric
from app.models.short_reaction import ShortReaction
from app.models.user import User
from app.schemas.comment import CommentCreateIn, CommentDeleteOut, CommentOut, CommentReactionIn, CommentReactionOut
from app.schemas.short import ShortBookmarkIn, ShortBookmarkOut, ShortOut, ShortReactionIn, ShortReactionOut

router = APIRouter(prefix="/shorts", tags=["shorts"])


def _short_or_404(short_id: int, db: Session) -> Short:
    short = db.scalar(select(Short).where(Short.id == short_id))
    if short is None:
        raise HTTPException(status_code=404, detail="Short not found")
    return short


def _get_or_create_metric(db: Session, short_id: int) -> ShortMetric:
    metric = db.get(ShortMetric, short_id)
    if metric is None:
        metric = ShortMetric(short_id=short_id)
        db.add(metric)
        db.flush()
    return metric


def _attach_metrics(short: Short, db: Session, viewer_user_id: int | None = None) -> dict:
    obj = {c: getattr(short, c, None) for c in short.__mapper__.column_attrs.keys()}
    metric = db.get(ShortMetric, short.id)
    obj["likes_count"] = metric.likes_count if metric else 0
    obj["comments_count"] = metric.comments_count if metric else 0
    obj["shares_count"] = metric.shares_count if metric else 0
    obj["bookmarks_count"] = getattr(metric, "bookmarks_count", 0) if metric else 0
    obj["views_count"] = metric.views_count if metric else 0
    obj["liked_by_viewer"] = False
    obj["bookmarked_by_viewer"] = False
    if viewer_user_id is not None:
        rxn = db.scalar(
            select(ShortReaction).where(
                ShortReaction.short_id == short.id,
                ShortReaction.user_id == viewer_user_id,
            )
        )
        obj["liked_by_viewer"] = rxn is not None
        bookmark = db.scalar(
            select(ShortBookmark).where(
                ShortBookmark.short_id == short.id,
                ShortBookmark.user_id == viewer_user_id,
            )
        )
        obj["bookmarked_by_viewer"] = bookmark is not None
    return obj


@router.get("/", response_model=list[ShortOut])
def list_shorts(
    language: str | None = Query(None, description="Filter by language code, e.g. 'kannada'"),
    category: str | None = Query(None, description="Filter by category"),
    viewer_user_id: int | None = Query(None, ge=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Return published public shorts, newest first."""
    stmt = (
        select(Short)
        .where(Short.status == "published", Short.visibility == "public")
    )
    if language:
        stmt = stmt.where(Short.language == language)
    if category:
        stmt = stmt.where(Short.category == category)
    stmt = stmt.order_by(Short.published_at.desc().nulls_last()).offset(offset).limit(limit)
    shorts = list(db.scalars(stmt).all())
    return [_attach_metrics(s, db, viewer_user_id) for s in shorts]


@router.get("/my", response_model=list[ShortOut])
def list_my_shorts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all shorts belonging to the authenticated user."""
    stmt = (
        select(Short)
        .where(Short.author_user_id == current_user.id)
        .order_by(Short.created_at.desc().nulls_last())
        .offset(offset)
        .limit(limit)
    )
    shorts = list(db.scalars(stmt).all())
    return [_attach_metrics(s, db, current_user.id) for s in shorts]


@router.get("/saved", response_model=list[ShortOut])
def list_saved_shorts(
    user_id: int = Query(..., ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ShortOut]:
    saved_short_ids: list[int] = list(
        db.execute(
            select(ShortBookmark.short_id)
            .where(ShortBookmark.user_id == user_id)
            .order_by(ShortBookmark.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
    )

    if not saved_short_ids:
        return []

    shorts = db.execute(
        select(Short).where(Short.id.in_(saved_short_ids))
    ).scalars().all()
    shorts_by_id = {short.id: short for short in shorts}
    ordered_shorts = [shorts_by_id[sid] for sid in saved_short_ids if sid in shorts_by_id]
    return [_attach_metrics(short, db, user_id) for short in ordered_shorts]


@router.get("/{short_id}", response_model=ShortOut)
def get_short(
    short_id: int,
    viewer_user_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    """Return a single published short."""
    short = _short_or_404(short_id, db)
    if short.status != "published" or short.visibility != "public":
        raise HTTPException(status_code=404, detail="Short not found")
    return _attach_metrics(short, db, viewer_user_id)


@router.post("/{short_id}/reactions", response_model=ShortReactionOut)
def react_to_short(
    short_id: int,
    payload: ShortReactionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShortReactionOut:
    """Toggle a reaction on a short. Repeated same reaction = unlike."""
    _short_or_404(short_id, db)
    actor_user_id = int(current_user.id)

    existing = db.scalar(
        select(ShortReaction).where(
            ShortReaction.short_id == short_id,
            ShortReaction.user_id == actor_user_id,
        )
    )

    metric = _get_or_create_metric(db, short_id)
    liked = True

    if existing is None:
        db.add(ShortReaction(
            short_id=short_id,
            user_id=actor_user_id,
            reaction_type=payload.reaction_type,
        ))
        metric.likes_count += 1
    elif existing.reaction_type == payload.reaction_type:
        db.delete(existing)
        metric.likes_count = max(0, metric.likes_count - 1)
        liked = False
    else:
        existing.reaction_type = payload.reaction_type

    metric.updated_at = datetime.now(timezone.utc)
    db.commit()

    return ShortReactionOut(
        ok=True,
        short_id=short_id,
        reaction_type=payload.reaction_type,
        likes_count=metric.likes_count,
        liked=liked,
    )


@router.post("/{short_id}/bookmarks", response_model=ShortBookmarkOut)
def toggle_short_bookmark(
    short_id: int,
    payload: ShortBookmarkIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShortBookmarkOut:
    _short_or_404(short_id, db)
    actor_user_id = int(current_user.id)

    viewer = db.get(User, actor_user_id)
    if viewer is None:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.execute(
        select(ShortBookmark).where(
            ShortBookmark.short_id == short_id,
            ShortBookmark.user_id == actor_user_id,
        )
    ).scalar_one_or_none()

    metric = _get_or_create_metric(db, short_id)
    if not hasattr(metric, "bookmarks_count"):
        raise HTTPException(status_code=500, detail="Short bookmarks are not available yet")

    bookmarked = True
    if existing is None:
        db.add(ShortBookmark(short_id=short_id, user_id=actor_user_id))
        metric.bookmarks_count = (metric.bookmarks_count or 0) + 1
    else:
        db.delete(existing)
        metric.bookmarks_count = max(0, (metric.bookmarks_count or 0) - 1)
        bookmarked = False

    metric.updated_at = datetime.now(timezone.utc)
    db.commit()

    return ShortBookmarkOut(
        ok=True,
        short_id=short_id,
        bookmarked=bookmarked,
        bookmarks_count=metric.bookmarks_count or 0,
    )


# ── Comments ──────────────────────────────────────────────────────────────────

def _map_short_comment_out(
    short_id: int,
    comment: ShortComment,
    users_by_id: dict[int, User],
    liked_by_viewer: bool = False,
) -> CommentOut:
    author = users_by_id.get(comment.user_id) if comment.user_id is not None else None
    author_avatar_display_url = None
    author_avatar_display_expires_at = None
    if author is not None:
        author_avatar_display_url, author_avatar_display_expires_at = build_avatar_display_url(author.avatar_url)

    return CommentOut(
        id=comment.id,
        post_id=short_id,
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


@router.get("/{short_id}/comments", response_model=list[CommentOut])
def list_short_comments(
    short_id: int,
    viewer_user_id: int | None = Query(default=None, ge=1),
    parent_comment_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[CommentOut]:
    _short_or_404(short_id, db)

    stmt = (
        select(ShortComment)
        .where(ShortComment.short_id == short_id, ShortComment.status == "published")
        .order_by(ShortComment.created_at.asc(), ShortComment.id.asc())
        .limit(limit)
        .offset(offset)
    )
    if parent_comment_id is not None:
        stmt = stmt.where(ShortComment.parent_comment_id == parent_comment_id)

    comments = db.execute(stmt).scalars().all()
    if not comments:
        return []

    user_ids = {c.user_id for c in comments if c.user_id is not None}
    users_by_id: dict[int, User] = {}
    if user_ids:
        users = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
        users_by_id = {u.id: u for u in users}

    liked_comment_ids: set[int] = set()
    if viewer_user_id is not None:
        comment_ids = [c.id for c in comments]
        liked_comment_ids = set(
            db.execute(
                select(ShortCommentReaction.comment_id).where(
                    ShortCommentReaction.comment_id.in_(comment_ids),
                    ShortCommentReaction.user_id == viewer_user_id,
                    ShortCommentReaction.reaction_type == "like",
                )
            ).scalars().all()
        )

    return [_map_short_comment_out(short_id, c, users_by_id, c.id in liked_comment_ids) for c in comments]


@router.post("/{short_id}/comments", response_model=CommentOut)
def create_short_comment(
    short_id: int,
    payload: CommentCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CommentOut:
    _short_or_404(short_id, db)
    actor_user_id = int(current_user.id)
    moderation = moderate_comment_text(payload.body)
    if not moderation.allowed:
        raise HTTPException(status_code=422, detail=moderation.reason or "Comment violates moderation guidelines.")

    parent: ShortComment | None = None
    if payload.parent_comment_id is not None:
        parent = db.get(ShortComment, payload.parent_comment_id)
        if parent is None or parent.short_id != short_id:
            raise HTTPException(status_code=400, detail="Invalid parent_comment_id")

    comment = ShortComment(
        short_id=short_id,
        user_id=actor_user_id,
        parent_comment_id=payload.parent_comment_id,
        body=payload.body.strip(),
        status="published",
    )
    db.add(comment)

    metric = _get_or_create_metric(db, short_id)
    metric.comments_count += 1
    metric.updated_at = datetime.now(timezone.utc)

    if parent is not None:
        parent.replies_count += 1
        parent.updated_at = datetime.now(timezone.utc)

    db.flush()

    try:
        if parent is not None and parent.user_id is not None and int(parent.user_id) != actor_user_id:
            create_notification(
                db,
                recipient_user_id=int(parent.user_id),
                actor_user_id=actor_user_id,
                notification_type="comment_reply",
                entity_type="short_comment",
                entity_id=int(parent.id),
                payload={
                    "kind": "short_comment_reply",
                    "short_id": int(short_id),
                    "parent_comment_id": int(parent.id),
                    "comment_id": int(comment.id),
                },
            )
    except Exception:
        pass

    db.commit()
    db.refresh(comment)
    author = db.get(User, actor_user_id)
    users_by_id = {author.id: author} if author is not None else {}
    return _map_short_comment_out(short_id, comment, users_by_id, liked_by_viewer=False)


@router.post("/{short_id}/comments/{comment_id}/reactions", response_model=CommentReactionOut)
def react_to_short_comment(
    short_id: int,
    comment_id: int,
    payload: CommentReactionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CommentReactionOut:
    _short_or_404(short_id, db)
    actor_user_id = int(current_user.id)

    comment = db.get(ShortComment, comment_id)
    if comment is None or comment.short_id != short_id or comment.status == "deleted":
        raise HTTPException(status_code=404, detail="Comment not found")

    existing = db.execute(
        select(ShortCommentReaction).where(
            ShortCommentReaction.comment_id == comment_id,
            ShortCommentReaction.user_id == actor_user_id,
        )
    ).scalar_one_or_none()

    liked = True
    if existing is None:
        db.add(ShortCommentReaction(
            comment_id=comment_id,
            user_id=actor_user_id,
            reaction_type=payload.reaction_type,
        ))
        comment.reactions_count += 1
        try:
            if comment.user_id is not None and int(comment.user_id) != actor_user_id:
                create_notification(
                    db,
                    recipient_user_id=int(comment.user_id),
                    actor_user_id=actor_user_id,
                    notification_type="post_reaction",
                    entity_type="short_comment",
                    entity_id=int(comment_id),
                    payload={
                        "kind": "short_comment_reaction",
                        "short_id": int(short_id),
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
        post_id=short_id,
        comment_id=comment_id,
        reaction_type=payload.reaction_type,
        reactions_count=comment.reactions_count,
        liked=liked,
    )


@router.delete("/{short_id}/comments/{comment_id}", response_model=CommentDeleteOut)
def delete_short_comment(
    short_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CommentDeleteOut:
    _short_or_404(short_id, db)
    actor_user_id = int(current_user.id)

    comment = db.get(ShortComment, comment_id)
    if comment is None or comment.short_id != short_id:
        raise HTTPException(status_code=404, detail="Comment not found")

    if comment.user_id != actor_user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own comment")

    comments_to_delete: list[ShortComment] = [comment]
    direct_replies = db.execute(
        select(ShortComment).where(
            ShortComment.short_id == short_id,
            ShortComment.parent_comment_id == comment.id,
            ShortComment.status != "deleted",
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
        parent = db.get(ShortComment, comment.parent_comment_id)
        if parent is not None:
            parent.replies_count = max(0, parent.replies_count - 1)
            parent.updated_at = datetime.now(timezone.utc)

    if deleted_count > 0:
        metric = _get_or_create_metric(db, short_id)
        metric.comments_count = max(0, metric.comments_count - deleted_count)
        metric.updated_at = datetime.now(timezone.utc)

    db.commit()

    return CommentDeleteOut(
        ok=True,
        post_id=short_id,
        comment_id=comment_id,
        deleted_count=deleted_count,
    )
