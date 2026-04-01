from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ReportEntityType = Literal["post", "comment", "comic_comment", "user"]
ReportReason = Literal["spam", "harassment", "misinformation", "nudity", "hate_speech", "other"]


class BlockOut(BaseModel):
    blocker_user_id: int
    blocked_user_id: int
    blocked: bool  # True = now blocked, False = unblocked


class BlockedUserOut(BaseModel):
    id: int
    username: str
    display_name: str
    avatar_url: str | None = None
    blocked_at: datetime

    model_config = {"from_attributes": True}


class ReportIn(BaseModel):
    entity_type: ReportEntityType
    entity_id: int = Field(..., ge=1)
    reason: ReportReason
    detail: str | None = Field(default=None, max_length=500)


class ReportOut(BaseModel):
    id: int
    reporter_user_id: int
    entity_type: str
    entity_id: int
    reason: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
