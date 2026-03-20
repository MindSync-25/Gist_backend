from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VoiceTake(Base):
    """A user's comment/take on a voice issue, optionally carrying a stance."""
    __tablename__ = "voice_takes"
    __table_args__ = (
        CheckConstraint(
            "stance IN ('support', 'oppose', 'question')",
            name="ck_voice_takes_stance",
        ),
        CheckConstraint(
            "status IN ('published', 'hidden', 'deleted')",
            name="ck_voice_takes_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    issue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("voice_issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_take_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("voice_takes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    stance: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reactions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replies_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
