from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.character import Character
from app.schemas.character import CharacterOut

router = APIRouter(prefix="/characters", tags=["characters"])


@router.get("", response_model=list[CharacterOut])
def list_characters(
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[CharacterOut]:
    stmt = select(Character).order_by(Character.sort_order.asc(), Character.id.asc())
    if not include_inactive:
        stmt = stmt.where(Character.is_active.is_(True))
    return db.execute(stmt).scalars().all()
