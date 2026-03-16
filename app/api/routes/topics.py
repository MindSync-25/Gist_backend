from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.topic import Topic
from app.schemas.topic import TopicOut

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("", response_model=list[TopicOut])
def list_topics(
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[TopicOut]:
    stmt = select(Topic).order_by(Topic.sort_order.asc(), Topic.id.asc())
    if not include_inactive:
        stmt = stmt.where(Topic.is_active.is_(True))
    return db.execute(stmt).scalars().all()
