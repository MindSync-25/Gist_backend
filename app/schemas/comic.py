from datetime import date, datetime

from pydantic import BaseModel


class ComicOut(BaseModel):
    id: int
    linked_post_id: int | None = None
    article_url: str
    headline: str | None = None
    category: str | None = None
    run_date: date
    tone: str | None = None
    summary: str | None = None
    banner_title: str | None = None
    scene: str | None = None
    hero_character: str | None = None
    background: str | None = None
    dialogue: dict | list | None = None
    image_prompt: str | None = None
    localized_copy: dict | None = None
    s3_key: str | None = None
    s3_url: str | None = None
    generated_at: datetime | None = None
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    liked_by_viewer: bool = False

    model_config = {"from_attributes": True}
