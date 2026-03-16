from datetime import datetime

from pydantic import BaseModel, Field


class PostOut(BaseModel):
    id: int
    source_type: str
    comic_id: int | None = None
    author_user_id: int | None = None
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


class PostReactionIn(BaseModel):
    user_id: int = Field(gt=0)
    reaction_type: str = Field(pattern="^(like|fire|lol)$")


class PostReactionOut(BaseModel):
    ok: bool
    post_id: int
    reaction_type: str
    likes_count: int
