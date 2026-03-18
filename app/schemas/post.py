from datetime import datetime

from pydantic import BaseModel, Field


class PostOut(BaseModel):
    id: int
    source_type: str
    comic_id: int | None = None
    author_user_id: int | None = None
    author_username: str | None = None
    author_display_name: str | None = None
    author_avatar_url: str | None = None
    author_avatar_display_url: str | None = None
    author_avatar_display_expires_at: datetime | None = None
    character_id: int | None = None
    topic_id: int | None = None
    series_id: int | None = None
    title: str
    description: str
    context: str
    image_url: str | None = None
    image_aspect_ratio: float | None = None
    format: str
    status: str
    published_at: datetime
    created_at: datetime
    updated_at: datetime
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    bookmarks_count: int = 0
    liked_by_viewer: bool = False
    bookmarked_by_viewer: bool = False


class PostCreateIn(BaseModel):
    author_user_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=180)
    description: str = ""
    context: str = ""
    image_url: str | None = None
    image_aspect_ratio: float | None = Field(default=None, gt=0, le=10)
    format: str = Field(
        default="hero",
        pattern="^(hero|conversation|editorial|floating|magazine|immersive|x-thread)$",
    )
    character_id: int | None = Field(default=None, gt=0)
    topic_id: int | None = Field(default=None, gt=0)
    series_id: int | None = Field(default=None, gt=0)


class PostCreateOut(BaseModel):
    post: "PostOut"


class PostReactionIn(BaseModel):
    user_id: int = Field(gt=0)
    reaction_type: str = Field(pattern="^(like|fire|lol)$")


class PostReactionOut(BaseModel):
    ok: bool
    post_id: int
    reaction_type: str
    likes_count: int
    liked: bool


class PostShareIn(BaseModel):
    user_id: int = Field(gt=0)
    channel: str = Field(default="native_share", pattern="^(copy_link|native_share|external_social|dm)$")


class PostShareOut(BaseModel):
    ok: bool
    post_id: int
    shares_count: int


class PostBookmarkIn(BaseModel):
    user_id: int = Field(gt=0)


class PostBookmarkOut(BaseModel):
    ok: bool
    post_id: int
    bookmarked: bool
    bookmarks_count: int
class PostUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=180)
    description: str | None = Field(default=None, max_length=800)
    context: str | None = Field(default=None)

class PostDeleteOut(BaseModel):
    ok: bool
    post_id: int
