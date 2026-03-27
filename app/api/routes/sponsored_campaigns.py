from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.sponsored_campaign import SponsoredCampaign
from app.schemas.sponsored_campaign import SponsoredCampaignOut

router = APIRouter(prefix="/sponsored-campaigns", tags=["sponsored-campaigns"])


@router.get("", response_model=list[SponsoredCampaignOut])
def list_sponsored_campaigns(
    placement: str = Query(default="home_feed"),
    active_only: bool = Query(default=True),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[SponsoredCampaignOut]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(SponsoredCampaign)
        .where(SponsoredCampaign.placement == placement)
        .order_by(SponsoredCampaign.priority.asc(), SponsoredCampaign.id.desc())
        .limit(limit)
    )

    if active_only:
        stmt = stmt.where(
            SponsoredCampaign.is_active.is_(True),
            or_(SponsoredCampaign.starts_at.is_(None), SponsoredCampaign.starts_at <= now),
            or_(SponsoredCampaign.ends_at.is_(None), SponsoredCampaign.ends_at >= now),
        )

    campaigns = db.execute(stmt).scalars().all()
    return [
        SponsoredCampaignOut(
            id=campaign.id,
            placement=campaign.placement,
            sponsor_name=campaign.sponsor_name,
            headline=campaign.headline,
            body=campaign.body,
            cta_label=campaign.cta_label,
            target_url=campaign.target_url,
            image_url=campaign.image_url,
            category=campaign.category,
            priority=campaign.priority,
            ad_network=campaign.ad_network,
            ad_unit_id=campaign.ad_unit_id,
            starts_at=campaign.starts_at,
            ends_at=campaign.ends_at,
        )
        for campaign in campaigns
    ]
