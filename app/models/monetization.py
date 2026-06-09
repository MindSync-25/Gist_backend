from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MonetizationProfile(Base):
    __tablename__ = "monetization_profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    monetization_unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wallet_balance_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_earned_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_withdrawn_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ContentViewEvent(Base):
    __tablename__ = "content_view_events"
    __table_args__ = (
        CheckConstraint("content_type IN ('post', 'short', 'comic')", name="ck_content_view_events_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    viewer_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    session_key: Mapped[str | None] = mapped_column(String(120), nullable=True)


class AdRevenueEvent(Base):
    __tablename__ = "ad_revenue_events"
    __table_args__ = (
        CheckConstraint("content_type IN ('post', 'short', 'comic')", name="ck_ad_revenue_events_type"),
        UniqueConstraint("external_event_id", name="uq_ad_revenue_events_external_event_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gross_revenue_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    creator_share_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gist_share_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_at_event: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_video_content: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revenue_source: Mapped[str] = mapped_column(String(40), nullable=False, default="ad_network")
    external_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'paid', 'rejected', 'cancelled')", name="ck_withdrawal_requests_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    payout_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payout_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
