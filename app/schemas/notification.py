from datetime import datetime
from typing import Any

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: int
    recipient_user_id: int
    actor_user_id: int | None = None
    actor_display_name: str | None = None
    actor_avatar_url: str | None = None
    actor_avatar_display_url: str | None = None
    actor_avatar_display_expires_at: datetime | None = None
    notification_type: str
    entity_type: str | None = None
    entity_id: int | None = None
    payload: dict[str, Any]
    is_read: bool
    created_at: datetime
    read_at: datetime | None = None


class NotificationReadOut(BaseModel):
    ok: bool
    notification_id: int
    is_read: bool


class NotificationReadAllOut(BaseModel):
    ok: bool
    marked_count: int


class NotificationUnreadCountOut(BaseModel):
    unread_count: int
