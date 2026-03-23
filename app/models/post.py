from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint("source_type IN ('native', 'comic_pipeline')", name="ck_posts_source_type"),
        CheckConstraint(
            "format IN ('hero', 'conversation', 'editorial', 'floating', 'magazine', 'immersive', 'x-thread')",
            name="ck_posts_format",
        ),
        CheckConstraint("status IN ('draft', 'published', 'archived', 'deleted')", name="ck_posts_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="native")
    comic_id: Mapped[int | None] = mapped_column(ForeignKey("comics.id", ondelete="SET NULL"), nullable=True, index=True)
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    character_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"), nullable=True, index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_aspect_ratio: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    image_style: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="hero")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
