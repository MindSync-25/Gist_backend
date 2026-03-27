from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConversationCreateDirectIn(BaseModel):
    other_user_id: int = Field(gt=0)


class MessageCreateIn(BaseModel):
    body: str | None = Field(default=None, max_length=4000)
    message_type: Literal["text", "post_share"] = "text"
    shared_post_id: int | None = Field(default=None, gt=0)


class ConversationParticipantOut(BaseModel):
    user_id: int
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


class ConversationOut(BaseModel):
    id: str
    conversation_type: str
    participants: list[ConversationParticipantOut]
    last_message_preview: str
    last_message_at: str
    unread_count: int
    updated_at: str


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    sender_user_id: int | None = None
    sender_username: str | None = None
    sender_display_name: str | None = None
    body: str | None = None
    message_type: str
    shared_post_id: int | None = None
    created_at: str


class MessageDeleteOut(BaseModel):
    ok: bool
    conversation_id: str
    message_id: str
