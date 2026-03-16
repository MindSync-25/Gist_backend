from datetime import datetime

from pydantic import BaseModel, Field


class CommentOut(BaseModel):
    id: int
    post_id: int
    user_id: int | None = None
    parent_comment_id: int | None = None
    body: str
    status: str
    reactions_count: int
    replies_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommentCreateIn(BaseModel):
    user_id: int = Field(gt=0)
    body: str = Field(min_length=1, max_length=5000)
    parent_comment_id: int | None = Field(default=None, gt=0)
