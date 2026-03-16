from datetime import datetime

from pydantic import BaseModel


class TopicOut(BaseModel):
    id: int
    slug: str
    label: str
    description: str | None = None
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
