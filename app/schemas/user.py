from datetime import datetime

from pydantic import BaseModel


class PublicUserOut(BaseModel):
    id: int
    username: str
    display_name: str
    bio: str | None = None
    location: str | None = None
    avatar_url: str | None = None
    avatar_display_url: str | None = None
    avatar_display_expires_at: datetime | None = None
    followers_count: int = 0
    following_count: int = 0
    is_following: bool = False

    model_config = {"from_attributes": True}


class FollowOut(BaseModel):
    follower_user_id: int
    followed_user_id: int
    following: bool
