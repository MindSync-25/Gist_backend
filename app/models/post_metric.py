from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PostMetric(Base):
    __tablename__ = "post_metrics"

    post_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    likes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comments_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shares_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bookmarks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
