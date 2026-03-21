from datetime import datetime

from pydantic import BaseModel


class SeriesOut(BaseModel):
    id: int
    slug: str
    title: str
    description: str | None = None
    cover_image_url: str | None = None
    created_by_user_id: int | None = None
    is_published: bool
    followers_count: int = 0
    items_count: int = 0
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # viewer-specific
    subscribed_by_viewer: bool = False


class SeriesItemOut(BaseModel):
    id: int
    series_id: int
    post_id: int | None = None
    title: str
    summary: str | None = None
    image_url: str | None = None
    position: int
    duration_seconds: int | None = None
    published_at: datetime | None = None
    created_at: datetime


class SeriesDetailOut(SeriesOut):
    items: list[SeriesItemOut] = []


class SeriesSubscribeOut(BaseModel):
    series_id: int
    user_id: int
    subscribed: bool
