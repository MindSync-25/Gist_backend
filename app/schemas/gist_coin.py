from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ContentType = Literal["post", "short"]


class GistCoinWalletOut(BaseModel):
    user_id: int
    balance_coins: int
    coin_usd_cents: int = 1
    total_received_coins: int
    total_spent_coins: int


class GistCoinTransactionOut(BaseModel):
    id: int
    user_id: int
    direction: str
    transaction_type: str
    amount_coins: int
    balance_after_coins: int
    counterparty_user_id: int | None = None
    content_type: str | None = None
    content_id: int | None = None
    reference_type: str | None = None
    reference_id: int | None = None
    note: str | None = None
    created_at: datetime


class TipCreateIn(BaseModel):
    content_type: ContentType
    content_id: int = Field(gt=0)
    amount_coins: int = Field(gt=0, le=1_000_000)
    message: str | None = Field(default=None, max_length=240)


class TipTransactionOut(BaseModel):
    id: int
    sender_user_id: int
    recipient_user_id: int
    content_type: ContentType
    content_id: int
    amount_coins: int
    creator_share_coins: int
    platform_fee_coins: int
    status: str
    message: str | None = None
    created_at: datetime
    sender_balance_coins: int


class TipSummaryOut(BaseModel):
    content_type: ContentType
    content_id: int
    tips_count: int
    total_tip_coins: int
    total_creator_share_coins: int


class CoinGrantIn(BaseModel):
    user_id: int = Field(gt=0)
    amount_coins: int = Field(gt=0, le=100_000_000)
    note: str | None = Field(default=None, max_length=240)


class CoinTopUpIn(BaseModel):
    user_id: int = Field(gt=0)
    amount_coins: int = Field(gt=0, le=100_000_000)
    provider_reference_id: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=240)


class TopUpRequestIn(BaseModel):
    amount_coins: int = Field(gt=0, le=100_000_000)
    source: str | None = Field(default="app", max_length=32)
    provider_reference_id: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=240)


class StripeCheckoutSessionCreateIn(BaseModel):
    amount_coins: int = Field(gt=0, le=100_000_000)
    source: str | None = Field(default="stripe", max_length=32)
    success_url: str | None = Field(default=None, max_length=500)
    cancel_url: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=240)


class StripeCheckoutSessionOut(BaseModel):
    top_up_request_id: int
    amount_coins: int
    amount_usd_cents: int
    session_id: str
    session_url: str
    provider_reference_id: str


class TopUpRequestOut(BaseModel):
    id: int
    user_id: int
    amount_coins: int
    status: str
    source: str | None = None
    provider_reference_id: str | None = None
    note: str | None = None
    requested_at: datetime
    updated_at: datetime


class TopUpRequestAdminUpdateIn(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected|cancelled)$")
    provider_reference_id: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=240)
