from sqlalchemy import BigInteger, Column, Float, Numeric, String, Text, TIMESTAMP, ARRAY
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class Short(Base):
    __tablename__ = "shorts"

    id                  = Column(BigInteger, primary_key=True)
    author_user_id      = Column(BigInteger, nullable=True)
    source_type         = Column(String(30), nullable=False, default="pipeline_generated")
    title               = Column(String(180), nullable=True)
    description         = Column(Text, default="")
    r2_object_key       = Column(Text, nullable=True)
    r2_public_url       = Column(Text, nullable=True)
    r2_bucket           = Column(String(80), nullable=True)
    thumbnail_url       = Column(Text, nullable=True)
    duration_seconds    = Column(Float, nullable=True)
    aspect_ratio        = Column(Numeric(5, 2), nullable=True)
    music_track_id      = Column(BigInteger, nullable=True)
    music_start_seconds = Column(Float, nullable=True)
    topic_id            = Column(BigInteger, nullable=True)
    character_id        = Column(BigInteger, nullable=True)
    pipeline_run_id     = Column(String(80), nullable=True)
    render_details      = Column(JSONB, nullable=True)
    status              = Column(String(20), default="published")
    visibility          = Column(String(20), default="public")
    category            = Column(String(30), nullable=True)
    language            = Column(String(30), nullable=True)
    tags                = Column(ARRAY(Text), nullable=True)
    published_at        = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at          = Column(TIMESTAMP(timezone=True))
    updated_at          = Column(TIMESTAMP(timezone=True))
