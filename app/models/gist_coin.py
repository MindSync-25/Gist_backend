from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GistCoinWallet(Base):
    __tablename__ = "gist_coin_wallets"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    balance_coins: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_received_coins: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_spent_coins: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GistCoinTransaction(Base):
    __tablename__ = "gist_coin_transactions"
    __table_args__ = (
        CheckConstraint("direction IN ('credit', 'debit')", name="ck_gist_coin_transactions_direction"),
        CheckConstraint("transaction_type IN ('tip_sent', 'tip_received', 'platform_fee', 'admin_grant', 'purchase')", name="ck_gist_coin_transactions_type"),
        CheckConstraint("amount_coins > 0", name="ck_gist_coin_transactions_amount_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount_coins: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_coins: Mapped[int] = mapped_column(BigInteger, nullable=False)
    counterparty_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    content_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GistTipTransaction(Base):
    __tablename__ = "gist_tip_transactions"
    __table_args__ = (
        CheckConstraint("content_type IN ('post', 'short')", name="ck_gist_tip_transactions_content_type"),
        CheckConstraint("amount_coins > 0", name="ck_gist_tip_transactions_amount_positive"),
        CheckConstraint("creator_share_coins >= 0", name="ck_gist_tip_transactions_creator_share_nonnegative"),
        CheckConstraint("platform_fee_coins >= 0", name="ck_gist_tip_transactions_platform_fee_nonnegative"),
        CheckConstraint("status IN ('succeeded', 'failed', 'refunded')", name="ck_gist_tip_transactions_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sender_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipient_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_coins: Mapped[int] = mapped_column(BigInteger, nullable=False)
    creator_share_coins: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_coins: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GistCoinTopUpRequest(Base):
    __tablename__ = "gist_coin_top_up_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_gist_coin_top_up_requests_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount_coins: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_reference_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
