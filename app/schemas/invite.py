from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class InviteCreateIn(BaseModel):
    invite_type: Literal["generic", "profile", "post", "voice"] = "generic"
    channel: Literal["native_share", "copy_link", "external_social", "dm"] = "native_share"
    target_entity_type: Literal["profile", "post", "voice"] | None = None
    target_entity_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_target(self) -> "InviteCreateIn":
        if self.invite_type == "generic":
            return self
        if self.target_entity_type is None or self.target_entity_id is None:
            raise ValueError("target_entity_type and target_entity_id are required for targeted invites")
        return self


class InviteLinkOut(BaseModel):
    id: int
    token: str
    share_url: str
    inviter_user_id: int
    invite_type: str
    target_entity_type: str | None = None
    target_entity_id: int | None = None
    channel: str
    opens_count: int = 0
    signups_count: int = 0
    activations_count: int = 0
    last_opened_at: datetime | None = None
    created_at: datetime


class InviteResolveIn(BaseModel):
    token: str = Field(min_length=8, max_length=120)


class InviteResolveOut(BaseModel):
    id: int
    token: str
    share_url: str
    inviter_user_id: int
    inviter_display_name: str
    inviter_username: str
    inviter_avatar_url: str | None = None
    invite_type: str
    target_entity_type: str | None = None
    target_entity_id: int | None = None
    channel: str
    opens_count: int = 0
    last_opened_at: datetime | None = None
    created_at: datetime


class InviteDashboardOut(BaseModel):
    links_count: int
    opens_count: int
    signups_count: int
    activations_count: int
    reward_points: int
    links: list[InviteLinkOut]