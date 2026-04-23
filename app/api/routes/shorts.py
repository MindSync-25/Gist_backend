from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.short import Short
from app.models.short_metric import ShortMetric
from app.models.short_reaction import ShortReaction
from app.models.user import User
from app.schemas.short import ShortOut, ShortReactionIn, ShortReactionOut

router = APIRouter(prefix="/shorts", tags=["shorts"])


def _short_or_404(short_id: int, db: Session) -> Short:
    short = db.scalar(select(Short).where(Short.id == short_id))
    if short is None:
        raise HTTPException(status_code=404, detail="Short not found")
    return short


def _get_or_create_metric(db: Session, short_id: int) -> ShortMetric:
    metric = db.get(ShortMetric, short_id)
    if metric is None:
        metric = ShortMetric(short_id=short_id)
        db.add(metric)
        db.flush()
    return metric


def _attach_metrics(short: Short, db: Session, viewer_user_id: int | None = None) -> dict:
    obj = {c: getattr(short, c, None) for c in short.__mapper__.column_attrs.keys()}
    metric = db.get(ShortMetric, short.id)
    obj["likes_count"] = metric.likes_count if metric else 0
    obj["comments_count"] = metric.comments_count if metric else 0
    obj["shares_count"] = metric.shares_count if metric else 0
    obj["views_count"] = metric.views_count if metric else 0
    obj["liked_by_viewer"] = False
    if viewer_user_id is not None:
        rxn = db.scalar(
            select(ShortReaction).where(
                ShortReaction.short_id == short.id,
                ShortReaction.user_id == viewer_user_id,
            )
        )
        obj["liked_by_viewer"] = rxn is not None
    return obj


@router.get("/", response_model=list[ShortOut])
def list_shorts(
    language: str | None = Query(None, description="Filter by language code, e.g. 'kannada'"),
    category: str | None = Query(None, description="Filter by category"),
    viewer_user_id: int | None = Query(None, ge=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Return published public shorts, newest first."""
    stmt = (
        select(Short)
        .where(Short.status == "published", Short.visibility == "public")
    )
    if language:
        stmt = stmt.where(Short.language == language)
    if category:
        stmt = stmt.where(Short.category == category)
    stmt = stmt.order_by(Short.published_at.desc().nulls_last()).offset(offset).limit(limit)
    shorts = list(db.scalars(stmt).all())
    return [_attach_metrics(s, db, viewer_user_id) for s in shorts]


@router.get("/my", response_model=list[ShortOut])
def list_my_shorts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all shorts belonging to the authenticated user."""
    stmt = (
        select(Short)
        .where(Short.author_user_id == current_user.id)
        .order_by(Short.created_at.desc().nulls_last())
        .offset(offset)
        .limit(limit)
    )
    shorts = list(db.scalars(stmt).all())
    return [_attach_metrics(s, db, current_user.id) for s in shorts]


@router.get("/{short_id}", response_model=ShortOut)
def get_short(
    short_id: int,
    viewer_user_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    """Return a single published short."""
    short = _short_or_404(short_id, db)
    if short.status != "published" or short.visibility != "public":
        raise HTTPException(status_code=404, detail="Short not found")
    return _attach_metrics(short, db, viewer_user_id)


@router.post("/{short_id}/reactions", response_model=ShortReactionOut)
def react_to_short(
    short_id: int,
    payload: ShortReactionIn,
    db: Session = Depends(get_db),
) -> ShortReactionOut:
    """Toggle a reaction on a short. Repeated same reaction = unlike."""
    _short_or_404(short_id, db)

    existing = db.scalar(
        select(ShortReaction).where(
            ShortReaction.short_id == short_id,
            ShortReaction.user_id == payload.user_id,
        )
    )

    metric = _get_or_create_metric(db, short_id)
    liked = True

    if existing is None:
        db.add(ShortReaction(
            short_id=short_id,
            user_id=payload.user_id,
            reaction_type=payload.reaction_type,
        ))
        metric.likes_count += 1
    elif existing.reaction_type == payload.reaction_type:
        db.delete(existing)
        metric.likes_count = max(0, metric.likes_count - 1)
        liked = False
    else:
        existing.reaction_type = payload.reaction_type

    metric.updated_at = datetime.now(timezone.utc)
    db.commit()

    return ShortReactionOut(
        ok=True,
        short_id=short_id,
        reaction_type=payload.reaction_type,
        likes_count=metric.likes_count,
        liked=liked,
    )

