from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.avatar_signing import build_avatar_display_url
from app.core.database import get_db
from app.models.comic import Comic
from app.models.follow import Follow
from app.models.post import Post
from app.models.short import Short
from app.models.topic import Topic
from app.models.user import User
from app.schemas.user import PublicUserOut
from app.schemas.topic import TopicOut

router = APIRouter(prefix="/search", tags=["search"])


def _compute_mutual_count(db: Session, viewer_user_id: int | None, target_user_id: int) -> int:
    if not viewer_user_id or viewer_user_id == target_user_id:
        return 0

    viewer_following = (
        select(Follow.followed_user_id)
        .where(Follow.follower_user_id == viewer_user_id)
        .subquery()
    )

    return int(
        db.scalar(
            select(func.count())
            .select_from(Follow)
            .join(
                viewer_following,
                Follow.follower_user_id == viewer_following.c.followed_user_id,
            )
            .where(Follow.followed_user_id == target_user_id)
        )
        or 0
    )


class PostSearchOut(BaseModel):
    id: int
    title: str
    context: str | None = None
    image_url: str | None = None
    author_username: str | None = None
    author_display_name: str | None = None
    author_avatar_url: str | None = None
    source_type: str = "native"

    model_config = {"from_attributes": True}


class SearchResults(BaseModel):
    users: list[PublicUserOut]
    topics: list[TopicOut]
    posts: list[PostSearchOut]


@router.get("", response_model=SearchResults)
def global_search(
    q: str = Query(default="", min_length=1, max_length=100),
    viewer_user_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> SearchResults:
    q = q.strip()
    if not q:
        return SearchResults(users=[], topics=[], posts=[])

    needle = f"%{q.lower()}%"

    # --- Users ---
    user_rows = db.execute(
        select(User)
        .where(
            User.is_active.is_(True),
            or_(
                func.lower(User.username).like(needle),
                func.lower(User.display_name).like(needle),
            ),
        )
        .order_by(User.display_name.asc())
        .limit(limit)
    ).scalars().all()

    users_out: list[PublicUserOut] = []
    for u in user_rows:
        followers_count = db.scalar(
            select(func.count()).select_from(Follow).where(Follow.followed_user_id == u.id)
        ) or 0
        following_count = db.scalar(
            select(func.count()).select_from(Follow).where(Follow.follower_user_id == u.id)
        ) or 0
        is_following = False
        if viewer_user_id and viewer_user_id != u.id:
            is_following = bool(
                db.scalar(
                    select(Follow).where(
                        Follow.follower_user_id == viewer_user_id,
                        Follow.followed_user_id == u.id,
                    )
                )
            )
        avatar_display_url, avatar_display_expires_at = build_avatar_display_url(u.avatar_url)
        mutual_count = _compute_mutual_count(db, viewer_user_id, u.id)
        users_out.append(PublicUserOut(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            bio=u.bio,
            location=u.location,
            avatar_url=u.avatar_url,
            avatar_display_url=avatar_display_url,
            avatar_display_expires_at=avatar_display_expires_at,
            followers_count=followers_count,
            following_count=following_count,
            mutual_count=mutual_count,
            is_following=is_following,
        ))

    # --- Topics ---
    topics_out = db.execute(
        select(Topic)
        .where(
            Topic.is_active.is_(True),
            or_(
                func.lower(Topic.label).like(needle),
                func.lower(Topic.slug).like(needle),
                func.lower(Topic.description).like(needle),
            ),
        )
        .order_by(Topic.sort_order.asc())
        .limit(limit)
    ).scalars().all()

    # --- Posts ---
    post_rows = db.execute(
        select(Post)
        .where(
            Post.status == "published",
            Post.visibility == "public",
            or_(
                func.lower(Post.title).like(needle),
                func.lower(Post.context).like(needle),
                func.lower(Post.description).like(needle),
            ),
        )
        .order_by(Post.published_at.desc())
        .limit(limit)
    ).scalars().all()

    # --- Shorts ---
    short_rows = db.execute(
        select(Short)
        .where(
            Short.status == "published",
            Short.visibility == "public",
            or_(
                func.lower(Short.title).like(needle),
                func.lower(Short.description).like(needle),
            ),
        )
        .order_by(Short.published_at.desc())
        .limit(limit)
    ).scalars().all()

    # --- Comics ---
    comic_rows = db.execute(
        select(Comic)
        .where(
            Comic.s3_url.isnot(None),
            or_(
                func.lower(Comic.headline).like(needle),
                func.lower(Comic.banner_title).like(needle),
                func.lower(Comic.summary).like(needle),
                func.lower(Comic.category).like(needle),
                func.lower(Comic.tone).like(needle),
                func.lower(Comic.scene).like(needle),
                func.lower(Comic.hero_character).like(needle),
            ),
        )
        .order_by(Comic.run_date.desc())
        .limit(limit)
    ).scalars().all()

    # Collect all author IDs from both posts and shorts
    author_ids = (
        {p.author_user_id for p in post_rows if p.author_user_id is not None}
        | {s.author_user_id for s in short_rows if s.author_user_id is not None}
    )
    authors_by_id: dict[int, User] = {}
    if author_ids:
        authors_by_id = {
            u.id: u for u in db.execute(select(User).where(User.id.in_(author_ids))).scalars().all()
        }

    posts_out: list[PostSearchOut] = []
    for p in post_rows:
        author = authors_by_id.get(p.author_user_id) if p.author_user_id else None
        posts_out.append(PostSearchOut(
            id=p.id,
            title=p.title or "",
            context=p.context,
            image_url=p.image_url,
            author_username=author.username if author else None,
            author_display_name=author.display_name if author else None,
            author_avatar_url=author.avatar_url if author else None,
            source_type=p.source_type,
        ))
    for s in short_rows:
        author = authors_by_id.get(s.author_user_id) if s.author_user_id else None
        posts_out.append(PostSearchOut(
            id=s.id,
            title=s.title or "",
            context=s.description,
            image_url=s.thumbnail_url,
            author_username=author.username if author else None,
            author_display_name=author.display_name if author else None,
            author_avatar_url=author.avatar_url if author else None,
            source_type="short",
        ))

    for c in comic_rows:
        posts_out.append(PostSearchOut(
            id=c.id,
            title=c.headline or c.banner_title or "",
            context=c.summary,
            image_url=c.s3_url,
            author_username=None,
            author_display_name=None,
            author_avatar_url=None,
            source_type="comic",
        ))

    # Sort: newest first across all types
    posts_out.sort(key=lambda x: x.source_type)

    return SearchResults(users=users_out, topics=list(topics_out), posts=posts_out)
