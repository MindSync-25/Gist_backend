from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ShortReaction(Base):
    __tablename__ = "short_reactions"
    __table_args__ = (
        UniqueConstraint("short_id", "user_id", name="uq_short_reactions_short_user"),
        CheckConstraint("reaction_type IN ('like', 'fire', 'lol')", name="ck_short_reactions_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    short_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shorts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
