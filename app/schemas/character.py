from datetime import datetime

from pydantic import BaseModel


class CharacterOut(BaseModel):
    id: int
    slug: str
    name: str
    handle: str
    role: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    accent_color: str | None = None
    followers_count: int
    posts_count: int
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
