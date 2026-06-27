from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConversationCreateDirectIn(BaseModel):
    other_user_id: int = Field(gt=0)


class ConversationCreateGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    member_user_ids: list[int] = Field(default_factory=list, max_length=99)
    description: str | None = Field(default=None, max_length=240)
    avatar_url: str | None = Field(default=None, max_length=1000)


class ConversationGroupUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=240)
    avatar_url: str | None = Field(default=None, max_length=1000)


class ConversationAddMembersIn(BaseModel):
    member_user_ids: list[int] = Field(min_length=1, max_length=99)


class ConversationMemberRoleUpdateIn(BaseModel):
    role: Literal["admin", "member"]


class MessageCreateIn(BaseModel):
    body: str | None = Field(default=None, max_length=4000)
    message_type: Literal["text", "post_share"] = "text"
    shared_post_id: int | None = Field(default=None, gt=0)


class ConversationParticipantOut(BaseModel):
    user_id: int
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    role: Literal["owner", "admin", "member"] | None = None


class ConversationOut(BaseModel):
    id: str
    conversation_type: str
    conversation_status: Literal["accepted", "request", "rejected", "archived", "left", "removed", "invited"] = "accepted"
    participants: list[ConversationParticipantOut]
    last_message_preview: str
    last_message_at: str
    unread_count: int
    updated_at: str
    group_name: str | None = None
    group_description: str | None = None
    group_avatar_url: str | None = None
    member_count: int | None = None
    current_user_role: Literal["owner", "admin", "member"] | None = None


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


class ConversationStatusUpdateOut(BaseModel):
    ok: bool
    conversation_id: str
    conversation_status: Literal["accepted", "request", "rejected", "archived", "left", "removed", "invited"]


class ConversationMemberUpdateOut(BaseModel):
    ok: bool
    conversation_id: str
    user_id: int
    role: Literal["owner", "admin", "member"] | None = None
    conversation_status: Literal["accepted", "left", "removed", "invited"] | None = None
