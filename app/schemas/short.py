from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.r2 import is_r2_url, presign_r2_get


class ShortOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    description: str = ""
    video_url: str | None = None       # mapped from r2_public_url
    thumbnail_url: str | None = None
    duration_seconds: float | None = None
    aspect_ratio: float | None = None
    category: str | None = None
    language: str | None = None
    tags: list[str] | None = None
    source_type: str = "pipeline_generated"
    status: str = "published"
    visibility: str = "public"
    topic_id: int | None = None
    character_id: int | None = None
    author_user_id: int | None = None
    published_at: datetime | None = None
    created_at: datetime | None = None
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    bookmarks_count: int = 0
    views_count: int = 0
    liked_by_viewer: bool = False
    bookmarked_by_viewer: bool = False

    @model_validator(mode="before")
    @classmethod
    def remap_fields(cls, data: Any) -> Any:
        """Map r2_public_url → video_url for ORM instances."""
        def _normalize_media_url(url: str | None) -> str | None:
            if not url:
                return url
            if "x-amz-signature=" in url.lower():
                return url
            if is_r2_url(url):
                return presign_r2_get(url)
            return url

        if hasattr(data, "__dict__"):
            # SQLAlchemy ORM row
            obj = {c: getattr(data, c, None) for c in data.__mapper__.column_attrs.keys()}
            obj["video_url"] = obj.pop("r2_public_url", None)
            obj["video_url"] = _normalize_media_url(obj.get("video_url"))
            obj["thumbnail_url"] = _normalize_media_url(obj.get("thumbnail_url"))
            return obj
        if isinstance(data, dict) and "r2_public_url" in data and "video_url" not in data:
            data = dict(data)
            data["video_url"] = data.pop("r2_public_url")
        if isinstance(data, dict):
            data = dict(data)
            data["video_url"] = _normalize_media_url(data.get("video_url"))
            data["thumbnail_url"] = _normalize_media_url(data.get("thumbnail_url"))
        return data


class ShortReactionIn(BaseModel):
    user_id: int
    reaction_type: str = "like"


class ShortReactionOut(BaseModel):
    ok: bool
    short_id: int
    reaction_type: str
    likes_count: int
    liked: bool


class ShortBookmarkIn(BaseModel):
    user_id: int


class ShortBookmarkOut(BaseModel):
    ok: bool
    short_id: int
    bookmarked: bool
    bookmarks_count: int
