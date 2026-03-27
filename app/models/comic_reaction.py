from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ComicReaction(Base):
    __tablename__ = "comic_reactions"
    __table_args__ = (
        UniqueConstraint("comic_id", "user_id", name="uq_comic_reactions_comic_user"),
        CheckConstraint("reaction_type IN ('like', 'fire', 'lol')", name="ck_comic_reactions_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    comic_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comics.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
