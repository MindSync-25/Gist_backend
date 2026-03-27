from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ComicComment(Base):
    __tablename__ = "comic_comments"
    __table_args__ = (
        CheckConstraint("status IN ('published', 'hidden', 'deleted')", name="ck_comic_comments_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    comic_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comics.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_comment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("comic_comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    reactions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replies_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
