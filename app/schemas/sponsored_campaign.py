from datetime import datetime

from pydantic import BaseModel


class SponsoredCampaignOut(BaseModel):
    id: int
    placement: str
    sponsor_name: str
    headline: str
    body: str
    cta_label: str
    target_url: str
    image_url: str | None = None
    category: str | None = None
    priority: int
    ad_network: str | None = None
    ad_unit_id: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
