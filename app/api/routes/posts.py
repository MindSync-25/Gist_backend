from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.comment import Comment
from app.models.post import Post
from app.models.post_metric import PostMetric
from app.models.post_reaction import PostReaction
from app.schemas.comment import CommentCreateIn, CommentOut
from app.schemas.post import PostOut, PostReactionIn, PostReactionOut

router = APIRouter(prefix="/posts", tags=["posts"])


def _map_post_out(post: Post, metric: PostMetric | None) -> PostOut:
    return PostOut(
        id=post.id,
        source_type=post.source_type,
        comic_id=post.comic_id,
        author_user_id=post.author_user_id,
        character_id=post.character_id,
        topic_id=post.topic_id,
        series_id=post.series_id,
        title=post.title,
        description=post.description,
        context=post.context,
        image_url=post.image_url,
        image_aspect_ratio=float(post.image_aspect_ratio) if post.image_aspect_ratio is not None else None,
        format=post.format,
        status=post.status,
        published_at=post.published_at,
        created_at=post.created_at,
        updated_at=post.updated_at,
        likes_count=metric.likes_count if metric else 0,
        comments_count=metric.comments_count if metric else 0,
        shares_count=metric.shares_count if metric else 0,
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


@router.get("", response_model=list[PostOut])
def list_posts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[PostOut]:
    posts = db.execute(
        select(Post)
        .where(Post.status == "published")
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

    return [_map_post_out(post, metric_by_post_id.get(post.id)) for post in posts]


@router.get("/{post_id}", response_model=PostOut)
def get_post(post_id: int, db: Session = Depends(get_db)) -> PostOut:
    post = _ensure_post_exists(db, post_id)
    metric = db.get(PostMetric, post_id)
    return _map_post_out(post, metric)


@router.get("/{post_id}/comments", response_model=list[CommentOut])
def list_post_comments(
    post_id: int,
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

    if parent_comment_id is None:
        stmt = stmt.where(Comment.parent_comment_id.is_(None))
    else:
        stmt = stmt.where(Comment.parent_comment_id == parent_comment_id)

    return db.execute(stmt).scalars().all()


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
    return comment


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

    if existing is None:
        db.add(
            PostReaction(
                post_id=post_id,
                user_id=payload.user_id,
                reaction_type=payload.reaction_type,
            )
        )
        metrics.likes_count += 1
    elif existing.reaction_type != payload.reaction_type:
        existing.reaction_type = payload.reaction_type

    metrics.updated_at = datetime.now(timezone.utc)

    db.commit()

    return PostReactionOut(
        ok=True,
        post_id=post_id,
        reaction_type=payload.reaction_type,
        likes_count=metrics.likes_count,
    )
