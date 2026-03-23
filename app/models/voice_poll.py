from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VoicePoll(Base):
    __tablename__ = "voice_polls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    label: Mapped[str] = mapped_column(String(60), nullable=False, default="LIVE POLL")
    question: Mapped[str] = mapped_column(String(280), nullable=False)
    issue_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("voice_issues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    total_votes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class VoicePollOption(Base):
    __tablename__ = "voice_poll_options"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("voice_polls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(140), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    votes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VoicePollVote(Base):
    """One row per (user, poll) — a user can only vote once per poll."""
    __tablename__ = "voice_poll_votes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("voice_polls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    option_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("voice_poll_options.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
