from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.series import Series, SeriesItem, SeriesSubscription
from app.schemas.series import SeriesDetailOut, SeriesItemOut, SeriesOut, SeriesSubscribeOut

router = APIRouter(prefix="/series", tags=["series"])


def _enrich_subscription(series_rows: list, viewer_user_id: int | None, db: Session) -> list[SeriesOut]:
    """Attach subscribed_by_viewer flag to a list of Series ORM rows."""
    if not series_rows:
        return []

    subscribed_ids: set[int] = set()
    if viewer_user_id:
        ids = [s.id for s in series_rows]
        subs = db.execute(
            select(SeriesSubscription.series_id).where(
                SeriesSubscription.series_id.in_(ids),
                SeriesSubscription.user_id == viewer_user_id,
            )
        ).scalars().all()
        subscribed_ids = set(subs)

    result = []
    for s in series_rows:
        out = SeriesOut.model_validate(s, from_attributes=True)
        out.subscribed_by_viewer = s.id in subscribed_ids
        result.append(out)
    return result


@router.get("", response_model=list[SeriesOut])
def list_series(
    viewer_user_id: int | None = Query(default=None, gt=0),
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List all published series, newest first."""
    stmt = select(Series).where(Series.is_published.is_(True))

    if q.strip():
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(Series.title).like(needle)
            | func.lower(func.coalesce(Series.description, "")).like(needle)
        )

    stmt = stmt.order_by(Series.published_at.desc().nulls_last(), Series.id.desc()).limit(limit).offset(offset)

    rows = db.execute(stmt).scalars().all()
    return _enrich_subscription(list(rows), viewer_user_id, db)


@router.get("/subscribed", response_model=list[SeriesOut])
def list_subscribed_series(
    user_id: int = Query(..., gt=0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Return series the given user is subscribed to, most recently subscribed first."""
    stmt = (
        select(Series)
        .join(SeriesSubscription, SeriesSubscription.series_id == Series.id)
        .where(SeriesSubscription.user_id == user_id)
        .order_by(SeriesSubscription.subscribed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).scalars().all()
    if not rows:
        return []

    # All are subscribed by definition
    result = []
    for s in rows:
        out = SeriesOut.model_validate(s, from_attributes=True)
        out.subscribed_by_viewer = True
        result.append(out)
    return result


@router.get("/{series_id}", response_model=SeriesDetailOut)
def get_series(
    series_id: int,
    viewer_user_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
):
    """Return a single series with its items."""
    series = db.get(Series, series_id)
    if not series or not series.is_published:
        raise HTTPException(status_code=404, detail="Series not found")

    items_rows = db.execute(
        select(SeriesItem)
        .where(SeriesItem.series_id == series_id)
        .order_by(SeriesItem.position.asc())
    ).scalars().all()

    subscribed = False
    if viewer_user_id:
        sub = db.get(SeriesSubscription, (series_id, viewer_user_id))
        subscribed = sub is not None

    out = SeriesDetailOut.model_validate(series, from_attributes=True)
    out.subscribed_by_viewer = subscribed
    out.items = [SeriesItemOut.model_validate(i, from_attributes=True) for i in items_rows]
    return out


@router.get("/{series_id}/items", response_model=list[SeriesItemOut])
def list_series_items(
    series_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Return paginated items for a series ordered by position."""
    series = db.get(Series, series_id)
    if not series or not series.is_published:
        raise HTTPException(status_code=404, detail="Series not found")

    rows = db.execute(
        select(SeriesItem)
        .where(SeriesItem.series_id == series_id)
        .order_by(SeriesItem.position.asc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return [SeriesItemOut.model_validate(i, from_attributes=True) for i in rows]


@router.post("/{series_id}/subscribe", response_model=SeriesSubscribeOut)
def toggle_subscribe(
    series_id: int,
    user_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
):
    """Toggle subscription for a user to a series. Returns current state."""
    series = db.get(Series, series_id)
    if not series or not series.is_published:
        raise HTTPException(status_code=404, detail="Series not found")

    existing = db.get(SeriesSubscription, (series_id, user_id))
    if existing:
        db.delete(existing)
        # decrement followers_count (floor at 0)
        series.followers_count = max(0, series.followers_count - 1)
        db.commit()
        return SeriesSubscribeOut(series_id=series_id, user_id=user_id, subscribed=False)

    sub = SeriesSubscription(series_id=series_id, user_id=user_id)
    db.add(sub)
    series.followers_count += 1
    db.commit()
    return SeriesSubscribeOut(series_id=series_id, user_id=user_id, subscribed=True)
