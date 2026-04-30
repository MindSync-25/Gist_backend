from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------

class VoiceIssueOut(BaseModel):
    id: int
    title: str
    context: str
    tags: list[str]
    created_by_type: str
    created_by_user_id: int | None = None
    is_featured: bool
    support_count: int
    oppose_count: int
    question_count: int
    takes_count: int
    reacting_now: int  # sum of support + oppose + question
    cover_image_url: str | None = None
    expires_at: datetime | None = None
    created_at: datetime
    viewer_stance: str | None = None  # populated when viewer_user_id is provided

    class Config:
        from_attributes = True


class VoiceIssueCreateIn(BaseModel):
    user_id: int = Field(gt=0)
    title: str = Field(min_length=4, max_length=240)
    context: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=10)
    is_featured: bool = False
    cover_image_url: str | None = None
    expires_at: datetime | None = None  # e.g. now + 7 days; None = never expires


class VoiceIssueUpdateIn(BaseModel):
    """Partial update — all fields optional."""
    user_id: int = Field(gt=0)  # must match created_by_user_id
    title: str | None = Field(default=None, min_length=4, max_length=240)
    context: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = Field(default=None, max_length=10)
    is_featured: bool | None = None
    cover_image_url: str | None = None
    expires_at: datetime | None = None
    status: str | None = Field(default=None, pattern="^(open|closed|archived)$")


# ---------------------------------------------------------------------------
# Stances
# ---------------------------------------------------------------------------

class VoiceStanceIn(BaseModel):
    user_id: int = Field(gt=0)
    stance: str = Field(pattern="^(support|oppose|question)$")


class VoiceStanceOut(BaseModel):
    ok: bool
    issue_id: int
    stance: str
    support_count: int
    oppose_count: int
    question_count: int


# ---------------------------------------------------------------------------
# Takes (comments on an issue)
# ---------------------------------------------------------------------------

class VoiceTakeReplyOut(BaseModel):
    id: int
    parent_take_id: int | None = None
    author: str
    author_id: int | None = None
    author_avatar_url: str | None = None
    stance: str | None = None
    content: str
    audio_url: str | None = None
    audio_duration_sec: int | None = None
    created_at: datetime
    replies: list["VoiceTakeReplyOut"] = Field(default_factory=list)

    class Config:
        from_attributes = True


class VoiceTakeOut(BaseModel):
    id: int
    author: str
    author_id: int | None
    author_avatar_url: str | None = None
    stance: str | None
    content: str
    audio_url: str | None = None
    audio_duration_sec: int | None = None
    reactions_count: int
    replies_count: int
    created_at: datetime
    replies: list[VoiceTakeReplyOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class VoiceTakeCreateIn(BaseModel):
    user_id: int = Field(gt=0)
    body: str = Field(default="", min_length=0, max_length=2000)
    stance: str | None = Field(default=None, pattern="^(support|oppose|question)$")
    audio_url: str | None = Field(default=None, max_length=1024)
    audio_duration_sec: int | None = Field(default=None, ge=1, le=600)
    parent_take_id: int | None = Field(default=None, gt=0)
    reply_to_take_id: int | None = Field(default=None, gt=0)


class VoiceTakeDeleteOut(BaseModel):
    ok: bool
    issue_id: int
    take_id: int
    deleted_count: int


# ---------------------------------------------------------------------------
# Polls
# ---------------------------------------------------------------------------

class VoicePollOptionOut(BaseModel):
    id: int
    label: str
    percentage: float
    votes: int

    class Config:
        from_attributes = True


class VoicePollOut(BaseModel):
    id: int
    label: str
    question: str
    options: list[VoicePollOptionOut]
    total_votes: int
    closes_at: datetime | None
    time_info: str  # e.g. "Closes in 2h 14m"
    viewer_voted_option_id: int | None = None  # populated when viewer has voted
    cover_image_url: str | None = None

    class Config:
        from_attributes = True


class VoicePollCreateIn(BaseModel):
    user_id: int = Field(gt=0)
    question: str = Field(min_length=4, max_length=280)
    options: list[str] = Field(min_length=2, max_length=4)
    closes_in_hours: int = Field(default=24, ge=1, le=168)  # 1h – 7 days
    issue_id: int | None = None
    cover_image_url: str | None = None


class VoicePollVoteIn(BaseModel):
    user_id: int = Field(gt=0)
    option_id: int = Field(gt=0)


class VoicePollVoteOut(BaseModel):
    ok: bool
    poll_id: int
    option_id: int
    total_votes: int
    options: list[VoicePollOptionOut]


# ---------------------------------------------------------------------------
# Top Voices
# ---------------------------------------------------------------------------

class TopVoiceOut(BaseModel):
    id: int
    name: str
    label: str  # e.g. "Top Voice", "Sharpest Take"
    takes_count: int


class TopTakeOut(BaseModel):
    take_id: int
    issue_id: int
    issue_title: str
    author_id: int | None
    author_name: str
    author_avatar_url: str | None = None
    stance: str | None = None
    content: str
    reactions_count: int
    replies_count: int
    engagement_score: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Participation stream item
# ---------------------------------------------------------------------------

class ParticipationStreamItem(BaseModel):
    text: str


class VoiceUserActivityItemOut(BaseModel):
    id: str
    kind: str  # issue_created | take_created | stance_set | poll_voted
    created_at: datetime
    issue_id: int | None = None
    issue_title: str | None = None
    stance: str | None = None
    content: str | None = None
    poll_id: int | None = None
    poll_question: str | None = None


try:
    VoiceTakeReplyOut.model_rebuild()
except AttributeError:
    VoiceTakeReplyOut.update_forward_refs()
