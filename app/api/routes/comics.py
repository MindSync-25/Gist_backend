from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.comic import Comic
from app.schemas.comic import ComicOut

router = APIRouter(prefix="/comics", tags=["comics"])


@router.get("", response_model=list[ComicOut])
def list_comics(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ComicOut]:
    rows = db.execute(
        select(Comic)
        .where(func.coalesce(Comic.s3_url, "") != "")
        .order_by(desc(Comic.generated_at), desc(Comic.id))
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return rows
