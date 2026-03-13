from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Comic(Base):
    __tablename__ = "comics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    article_url: Mapped[str] = mapped_column(Text, nullable=False)
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    tone: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    banner_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene: Mapped[str | None] = mapped_column(Text, nullable=True)
    hero_character: Mapped[str | None] = mapped_column(Text, nullable=True)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialogue: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, server_default=func.now())
