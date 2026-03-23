from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VoiceIssue(Base):
    __tablename__ = "voice_issues"
    __table_args__ = (
        CheckConstraint(
            "created_by_type IN ('editorial', 'user')",
            name="ck_voice_issues_created_by_type",
        ),
        CheckConstraint(
            "status IN ('open', 'closed', 'archived')",
            name="voice_issues_status_check",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(300), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Comma-separated tag strings, e.g. "Trending,Politics,National"
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False, default="editorial")
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oppose_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    takes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
