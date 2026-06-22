from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VoiceLiveSession(Base):
    __tablename__ = "voice_live_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'ended')", name="ck_voice_live_sessions_status"),
        CheckConstraint("max_participants BETWEEN 2 AND 8", name="ck_voice_live_sessions_max_participants"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("voice_issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    host_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    room_slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="jitsi")
    join_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    max_participants: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VoiceLiveParticipant(Base):
    __tablename__ = "voice_live_participants"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_voice_live_participants_session_user"),
        CheckConstraint("role IN ('host', 'member')", name="ck_voice_live_participants_role"),
        CheckConstraint("status IN ('invited', 'joined', 'left')", name="ck_voice_live_participants_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("voice_live_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited", index=True)
    invited_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
