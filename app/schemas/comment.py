from datetime import datetime

from pydantic import BaseModel, Field


class CommentOut(BaseModel):
    id: int
    post_id: int
    user_id: int | None = None
    author_username: str | None = None
    author_display_name: str | None = None
    author_avatar_url: str | None = None
    author_avatar_display_url: str | None = None
    author_avatar_display_expires_at: datetime | None = None
    parent_comment_id: int | None = None
    body: str
    status: str
    reactions_count: int
    liked_by_viewer: bool = False
    replies_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommentCreateIn(BaseModel):
    user_id: int = Field(gt=0)
    body: str = Field(min_length=1, max_length=5000)
    parent_comment_id: int | None = Field(default=None, gt=0)


class CommentReactionIn(BaseModel):
    user_id: int = Field(gt=0)
    reaction_type: str = Field(default="like", pattern="^(like|fire|lol)$")


class CommentReactionOut(BaseModel):
    ok: bool
    post_id: int
    comment_id: int
    reaction_type: str
    reactions_count: int
    liked: bool
