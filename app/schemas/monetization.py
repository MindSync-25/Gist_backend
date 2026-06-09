from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ContentType = Literal["post", "short", "comic"]


class ContentViewIn(BaseModel):
    content_type: ContentType
    content_id: int = Field(gt=0)
    viewed_at: datetime | None = None
    source: str | None = Field(default=None, max_length=40)
    session_key: str | None = Field(default=None, max_length=120)


class ContentViewsIn(BaseModel):
    views: list[ContentViewIn] = Field(min_length=1, max_length=50)


class ContentViewsOut(BaseModel):
    recorded_count: int
    rolling_views_60d: int
    monetization_unlocked: bool
    monetization_unlocked_at: datetime | None = None


class AdRevenueIn(BaseModel):
    content_type: ContentType
    content_id: int = Field(gt=0)
    gross_revenue_cents: int = Field(ge=0)
    occurred_at: datetime | None = None
    revenue_source: str = Field(default="ad_network", max_length=40)
    external_event_id: str | None = Field(default=None, max_length=120)


class AdRevenueOut(BaseModel):
    id: int
    content_type: ContentType
    content_id: int
    owner_user_id: int
    gross_revenue_cents: int
    creator_share_cents: int
    gist_share_cents: int
    eligible_at_event: bool
    is_video_content: bool
    occurred_at: datetime


class WithdrawalRequestIn(BaseModel):
    amount_cents: int | None = Field(default=None, ge=5000)
    payout_method: str | None = Field(default=None, max_length=40)
    payout_note: str | None = Field(default=None, max_length=500)


class WithdrawalRequestOut(BaseModel):
    id: int
    amount_cents: int
    status: str
    payout_method: str | None = None
    payout_note: str | None = None
    requested_at: datetime
    updated_at: datetime


class MonetizationSummaryOut(BaseModel):
    user_id: int
    threshold_views: int = 100000
    rolling_window_days: int = 60
    rolling_views_60d: int
    monetization_unlocked: bool
    monetization_unlocked_at: datetime | None = None
    revenue_share_percent: int = 40
    payout_threshold_cents: int = 5000
    wallet_balance_cents: int
    total_earned_cents: int
    total_withdrawn_cents: int
    pending_withdrawal_cents: int
    recent_revenue_events: list[AdRevenueOut]
    withdrawals: list[WithdrawalRequestOut]
