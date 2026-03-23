from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.avatar_signing import build_avatar_display_url, extract_managed_user_upload_key
from app.core.config import get_settings
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.bookmark import Bookmark
from app.models.comment import Comment
from app.models.comment_reaction import CommentReaction
from app.models.post import Post
from app.models.post_metric import PostMetric
from app.models.post_reaction import PostReaction
from app.models.post_share import PostShare
from app.models.user import User
from app.schemas.comment import CommentCreateIn, CommentOut, CommentReactionIn, CommentReactionOut
from app.schemas.post import PostBookmarkIn, PostBookmarkOut, PostCreateIn, PostOut, PostReactionIn, PostReactionOut, PostShareIn, PostShareOut, PostUpdateIn, PostDeleteOut

router = APIRouter(prefix="/posts", tags=["posts"])


@lru_cache
def _s3_client():
    import boto3

    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.Session(**kwargs).client("s3", region_name=settings.aws_region)


def _resolve_image_url(image_url: str | None) -> str | None:
    if not image_url:
        return None

    # If we already have a presigned URL, keep it as-is.
    if "x-amz-signature=" in image_url.lower():
        return image_url

    parsed = urlparse(image_url)
    if parsed.scheme not in {"http", "https"}:
        return image_url

    settings = get_settings()
    expected_hosts = {
        f"{settings.s3_bucket_name}.s3.{settings.aws_region}.amazonaws.com",
        f"{settings.s3_bucket_name}.s3.amazonaws.com",
    }

    if parsed.netloc.lower() not in expected_hosts:
        return image_url

    object_key = parsed.path.lstrip("/")
    if not object_key:
        return image_url

    try:
        s3 = _s3_client()
        return s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.s3_bucket_name,
                "Key": object_key,
            },
            ExpiresIn=settings.s3_presign_expiry_seconds,
        )
    except Exception:
        # Keep the original URL as fallback if signing fails.
        return image_url


def _map_post_out(
    post: Post,
    metric: PostMetric | None,
    liked_by_viewer: bool = False,
    bookmarked_by_viewer: bool = False,
    author: User | None = None,
) -> PostOut:
    author_avatar_display_url = None
    author_avatar_display_expires_at = None
    if author is not None:
        author_avatar_display_url, author_avatar_display_expires_at = build_avatar_display_url(author.avatar_url)

    return PostOut(
        id=post.id,
        source_type=post.source_type,
        comic_id=post.comic_id,
        author_user_id=post.author_user_id,
        author_username=author.username if author else None,
        author_display_name=author.display_name if author else None,
        author_avatar_url=author.avatar_url if author else None,
        author_avatar_display_url=author_avatar_display_url,
        author_avatar_display_expires_at=author_avatar_display_expires_at,
        character_id=post.character_id,
        topic_id=post.topic_id,
        series_id=post.series_id,
        title=post.title,
        description=post.description,
        context=post.context,
        image_url=_resolve_image_url(post.image_url),
        image_aspect_ratio=float(post.image_aspect_ratio) if post.image_aspect_ratio is not None else None,
        image_style=post.image_style,
        format=post.format,
        status=post.status,
        published_at=post.published_at,
        created_at=post.created_at,
        updated_at=post.updated_at,
        likes_count=metric.likes_count if metric else 0,
        comments_count=metric.comments_count if metric else 0,
        shares_count=metric.shares_count if metric else 0,
        bookmarks_count=metric.bookmarks_count if metric else 0,
        liked_by_viewer=liked_by_viewer,
        bookmarked_by_viewer=bookmarked_by_viewer,
    )


def _get_or_create_metrics(db: Session, post_id: int) -> PostMetric:
    metric = db.get(PostMetric, post_id)
    if metric is None:
        metric = PostMetric(post_id=post_id)
        db.add(metric)
        db.flush()
    return metric


def _ensure_post_exists(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


def _map_comment_out(
    comment: Comment,
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
        post_id=comment.post_id,
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


def _delete_managed_image_from_s3(image_url: str | None) -> None:
    object_key = extract_managed_user_upload_key(image_url)
    if not object_key:
        return

    settings = get_settings()
    try:
        _s3_client().delete_object(Bucket=settings.s3_bucket_name, Key=object_key)
    except Exception:
        # Keep post deletion resilient even if storage cleanup fails.
        return


@router.post("", response_model=PostOut, status_code=201)
def create_post(payload: PostCreateIn, db: Session = Depends(get_db)) -> PostOut:
    now = datetime.now(timezone.utc)
    image_style_payload = payload.image_style.model_dump(exclude_none=True) if payload.image_style is not None else None
    if payload.image_url and not image_style_payload:
        # Keep style replay deterministic even for older clients that don't send image_style yet.
        image_style_payload = {
            "filter": "none",
            "frame": "none",
            "overlay_position": "bottom",
            "zoom": 1.0,
            "offset_x": 0.0,
            "offset_y": 0.0,
        }

    post = Post(
        source_type="native",
        author_user_id=payload.author_user_id,
        character_id=payload.character_id,
        topic_id=payload.topic_id,
        series_id=payload.series_id,
        title=payload.title,
        description=payload.description,
        context=payload.context,
        image_url=payload.image_url,
        image_aspect_ratio=payload.image_aspect_ratio,
        image_style=image_style_payload,
        format=payload.format,
        status="published",
        published_at=now,
    )
    db.add(post)
    db.flush()

    metric = PostMetric(post_id=post.id)
    db.add(metric)
    db.commit()
    db.refresh(post)
    db.refresh(metric)
    author = db.get(User, post.author_user_id) if post.author_user_id is not None else None

    return _map_post_out(post, metric, author=author)


@router.get("", response_model=list[PostOut])
def list_posts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    author_user_id: int | None = Query(default=None, ge=1),
    viewer_user_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> list[PostOut]:
    base_query = select(Post).where(Post.status == "published")

    if author_user_id is not None:
        base_query = base_query.where(Post.author_user_id == author_user_id)

    posts = db.execute(
        base_query
        .order_by(Post.published_at.desc(), Post.id.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    if not posts:
        return []

    post_ids = [post.id for post in posts]
    metrics = db.execute(
        select(PostMetric).where(PostMetric.post_id.in_(post_ids))
    ).scalars().all()
    metric_by_post_id = {metric.post_id: metric for metric in metrics}

    author_ids = {post.author_user_id for post in posts if post.author_user_id is not None}
    users_by_id: dict[int, User] = {}
    if author_ids:
        users = db.execute(
            select(User).where(User.id.in_(author_ids))
        ).scalars().all()
        users_by_id = {user.id: user for user in users}

    liked_post_ids: set[int] = set()
    bookmarked_post_ids: set[int] = set()
    if viewer_user_id is not None:
        liked_post_ids = set(
            db.execute(
                select(PostReaction.post_id).where(
                    PostReaction.post_id.in_(post_ids),
                    PostReaction.user_id == viewer_user_id,
                    PostReaction.reaction_type == "like",
                )
            ).scalars().all()
        )

        bookmarked_post_ids = set(
            db.execute(
                select(Bookmark.post_id).where(
                    Bookmark.post_id.in_(post_ids),
                    Bookmark.user_id == viewer_user_id,
                )
            ).scalars().all()
        )

    return [
        _map_post_out(
            post,
            metric_by_post_id.get(post.id),
            post.id in liked_post_ids,
            post.id in bookmarked_post_ids,
            users_by_id.get(post.author_user_id) if post.author_user_id is not None else None,
        )
        for post in posts
    ]


@router.get("/saved", response_model=list[PostOut])
def list_saved_posts(
    user_id: int = Query(..., ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[PostOut]:
    """Return posts that the given user has bookmarked, newest bookmark first."""
    saved_post_ids: list[int] = list(
        db.execute(
            select(Bookmark.post_id)
            .where(Bookmark.user_id == user_id)
            .order_by(Bookmark.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
    )

    if not saved_post_ids:
        return []

    posts = db.execute(
        select(Post).where(Post.id.in_(saved_post_ids))
    ).scalars().all()

    # Preserve bookmark recency order
    posts_by_id = {post.id: post for post in posts}
    ordered_posts = [posts_by_id[pid] for pid in saved_post_ids if pid in posts_by_id]

    metrics = db.execute(
        select(PostMetric).where(PostMetric.post_id.in_(saved_post_ids))
    ).scalars().all()
    metric_by_post_id = {m.post_id: m for m in metrics}

    author_ids = {post.author_user_id for post in ordered_posts if post.author_user_id is not None}
    users_by_id: dict[int, User] = {}
    if author_ids:
        users = db.execute(
            select(User).where(User.id.in_(author_ids))
        ).scalars().all()
        users_by_id = {user.id: user for user in users}

    liked_post_ids: set[int] = set(
        db.execute(
            select(PostReaction.post_id).where(
                PostReaction.post_id.in_(saved_post_ids),
                PostReaction.user_id == user_id,
                PostReaction.reaction_type == "like",
            )
        ).scalars().all()
    )

    return [
        _map_post_out(
            post,
            metric_by_post_id.get(post.id),
            liked_by_viewer=post.id in liked_post_ids,
            bookmarked_by_viewer=True,  # these are always bookmarked by definition
            author=users_by_id.get(post.author_user_id) if post.author_user_id is not None else None,
        )
        for post in ordered_posts
    ]


@router.get("/{post_id}", response_model=PostOut)
def get_post(
    post_id: int,
    viewer_user_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> PostOut:
    post = _ensure_post_exists(db, post_id)
    metric = db.get(PostMetric, post_id)
    liked_by_viewer = False
    bookmarked_by_viewer = False

    if viewer_user_id is not None:
        liked_by_viewer = (
            db.execute(
                select(PostReaction.id).where(
                    PostReaction.post_id == post_id,
                    PostReaction.user_id == viewer_user_id,
                    PostReaction.reaction_type == "like",
                )
            ).scalar_one_or_none()
            is not None
        )

        bookmarked_by_viewer = (
            db.execute(
                select(Bookmark.post_id).where(
                    Bookmark.post_id == post_id,
                    Bookmark.user_id == viewer_user_id,
                )
            ).scalar_one_or_none()
            is not None
        )

    author = db.get(User, post.author_user_id) if post.author_user_id is not None else None
    return _map_post_out(post, metric, liked_by_viewer, bookmarked_by_viewer, author)


@router.get("/{post_id}/comments", response_model=list[CommentOut])
def list_post_comments(
    post_id: int,
    viewer_user_id: int | None = Query(default=None, ge=1),
    parent_comment_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[CommentOut]:
    _ensure_post_exists(db, post_id)

    stmt = (
        select(Comment)
        .where(
            Comment.post_id == post_id,
            Comment.status != "deleted",
        )
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .limit(limit)
        .offset(offset)
    )

    if parent_comment_id is not None:
        stmt = stmt.where(Comment.parent_comment_id == parent_comment_id)

    comments = db.execute(stmt).scalars().all()
    if not comments:
        return []

    user_ids = {comment.user_id for comment in comments if comment.user_id is not None}
    users_by_id: dict[int, User] = {}

    if user_ids:
        users = db.execute(
            select(User).where(User.id.in_(user_ids))
        ).scalars().all()
        users_by_id = {user.id: user for user in users}

    liked_comment_ids: set[int] = set()
    if viewer_user_id is not None:
        comment_ids = [comment.id for comment in comments]
        liked_comment_ids = set(
            db.execute(
                select(CommentReaction.comment_id).where(
                    CommentReaction.comment_id.in_(comment_ids),
                    CommentReaction.user_id == viewer_user_id,
                    CommentReaction.reaction_type == "like",
                )
            ).scalars().all()
        )

    return [
        _map_comment_out(comment, users_by_id, comment.id in liked_comment_ids)
        for comment in comments
    ]


@router.post("/{post_id}/comments", response_model=CommentOut)
def create_comment(
    post_id: int,
    payload: CommentCreateIn,
    db: Session = Depends(get_db),
) -> CommentOut:
    _ensure_post_exists(db, post_id)

    if payload.parent_comment_id is not None:
        parent = db.get(Comment, payload.parent_comment_id)
        if parent is None or parent.post_id != post_id:
            raise HTTPException(status_code=400, detail="Invalid parent_comment_id")
    else:
        parent = None

    comment = Comment(
        post_id=post_id,
        user_id=payload.user_id,
        parent_comment_id=payload.parent_comment_id,
        body=payload.body.strip(),
        status="published",
    )
    db.add(comment)

    metrics = _get_or_create_metrics(db, post_id)
    metrics.comments_count += 1
    metrics.updated_at = datetime.now(timezone.utc)

    if parent is not None:
        parent.replies_count += 1
        parent.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(comment)

    author = db.get(User, payload.user_id)
    users_by_id = {author.id: author} if author is not None else {}
    return _map_comment_out(comment, users_by_id, liked_by_viewer=False)


@router.post("/{post_id}/comments/{comment_id}/reactions", response_model=CommentReactionOut)
def react_to_comment(
    post_id: int,
    comment_id: int,
    payload: CommentReactionIn,
    db: Session = Depends(get_db),
) -> CommentReactionOut:
    _ensure_post_exists(db, post_id)

    comment = db.get(Comment, comment_id)
    if comment is None or comment.post_id != post_id or comment.status == "deleted":
        raise HTTPException(status_code=404, detail="Comment not found")

    existing = db.execute(
        select(CommentReaction).where(
            CommentReaction.comment_id == comment_id,
            CommentReaction.user_id == payload.user_id,
        )
    ).scalar_one_or_none()

    liked = True

    if existing is None:
        db.add(
            CommentReaction(
                comment_id=comment_id,
                user_id=payload.user_id,
                reaction_type=payload.reaction_type,
            )
        )
        comment.reactions_count += 1
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
        post_id=post_id,
        comment_id=comment_id,
        reaction_type=payload.reaction_type,
        reactions_count=comment.reactions_count,
        liked=liked,
    )


@router.post("/{post_id}/reactions", response_model=PostReactionOut)
def react_to_post(
    post_id: int,
    payload: PostReactionIn,
    db: Session = Depends(get_db),
) -> PostReactionOut:
    _ensure_post_exists(db, post_id)

    existing = db.execute(
        select(PostReaction).where(
            PostReaction.post_id == post_id,
            PostReaction.user_id == payload.user_id,
        )
    ).scalar_one_or_none()

    metrics = _get_or_create_metrics(db, post_id)
    liked = True

    if existing is None:
        db.add(
            PostReaction(
                post_id=post_id,
                user_id=payload.user_id,
                reaction_type=payload.reaction_type,
            )
        )
        metrics.likes_count += 1
    elif existing.reaction_type == payload.reaction_type:
        db.delete(existing)
        metrics.likes_count = max(0, metrics.likes_count - 1)
        liked = False
    elif existing.reaction_type != payload.reaction_type:
        existing.reaction_type = payload.reaction_type

    metrics.updated_at = datetime.now(timezone.utc)

    db.commit()

    return PostReactionOut(
        ok=True,
        post_id=post_id,
        reaction_type=payload.reaction_type,
        likes_count=metrics.likes_count,
        liked=liked,
    )


@router.post("/{post_id}/shares", response_model=PostShareOut)
def share_post(
    post_id: int,
    payload: PostShareIn,
    db: Session = Depends(get_db),
) -> PostShareOut:
    _ensure_post_exists(db, post_id)

    db.add(
        PostShare(
            post_id=post_id,
            user_id=payload.user_id,
            channel=payload.channel,
        )
    )

    metrics = _get_or_create_metrics(db, post_id)
    metrics.shares_count += 1
    metrics.updated_at = datetime.now(timezone.utc)

    db.commit()

    return PostShareOut(
        ok=True,
        post_id=post_id,
        shares_count=metrics.shares_count,
    )


@router.post("/{post_id}/bookmarks", response_model=PostBookmarkOut)
def toggle_post_bookmark(
    post_id: int,
    payload: PostBookmarkIn,
    db: Session = Depends(get_db),
) -> PostBookmarkOut:
    _ensure_post_exists(db, post_id)

    existing = db.execute(
        select(Bookmark).where(
            Bookmark.post_id == post_id,
            Bookmark.user_id == payload.user_id,
        )
    ).scalar_one_or_none()

    metrics = _get_or_create_metrics(db, post_id)
    bookmarked = True

    if existing is None:
        db.add(
            Bookmark(
                post_id=post_id,
                user_id=payload.user_id,
            )
        )
        metrics.bookmarks_count += 1
    else:
        db.delete(existing)
        metrics.bookmarks_count = max(0, metrics.bookmarks_count - 1)
        bookmarked = False

    metrics.updated_at = datetime.now(timezone.utc)

    db.commit()

    return PostBookmarkOut(
        ok=True,
        post_id=post_id,
        bookmarked=bookmarked,
        bookmarks_count=metrics.bookmarks_count,
    )

@router.delete("/{post_id}", response_model=PostDeleteOut)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if post.author_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this post")

    _delete_managed_image_from_s3(post.image_url)
    db.delete(post)
    db.commit()

    return PostDeleteOut(ok=True, post_id=post_id)

@router.patch("/{post_id}", response_model=PostOut)
def update_post(
    post_id: int,
    payload: PostUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = db.query(Post).filter(Post.id == post_id, Post.status != "deleted").first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if post.author_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this post")

    if payload.title is not None:
        post.title = payload.title
    if payload.description is not None:
        post.description = payload.description
    if payload.context is not None:
        post.context = payload.context

    post.updated_at = datetime.now(timezone.utc)
    db.commit()

    return get_post(post_id=post.id, viewer_user_id=current_user.id, db=db)
