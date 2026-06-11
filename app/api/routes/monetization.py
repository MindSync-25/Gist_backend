from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models.comic import Comic
from app.models.monetization import AdRevenueEvent, ContentViewEvent, MonetizationProfile, WithdrawalRequest
from app.models.post import Post
from app.models.short import Short
from app.models.user import User
from app.schemas.monetization import (
    AdRevenueIn,
    AdRevenueOut,
    ContentViewsIn,
    ContentViewsOut,
    MonetizationSummaryOut,
    WithdrawalAdminUpdateIn,
    WithdrawalRequestIn,
    WithdrawalRequestOut,
)

router = APIRouter(prefix="/monetization", tags=["monetization"])

MONETIZATION_THRESHOLD_VIEWS = 100_000
MONETIZATION_WINDOW_DAYS = 60
CREATOR_REVENUE_SHARE_PERCENT = 40
PAYOUT_THRESHOLD_CENTS = 5_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(value: datetime | None) -> datetime:
    if value is None:
        return _now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _get_or_create_profile(db: Session, user_id: int) -> MonetizationProfile:
    profile = db.get(MonetizationProfile, user_id)
    if profile is None:
        profile = MonetizationProfile(user_id=user_id)
        db.add(profile)
        db.flush()
    return profile


def _rolling_views_60d(db: Session, user_id: int, at: datetime | None = None) -> int:
    anchor = _normalize_dt(at)
    window_start = anchor - timedelta(days=MONETIZATION_WINDOW_DAYS)
    return int(
        db.scalar(
            select(func.count())
            .select_from(ContentViewEvent)
            .where(
                ContentViewEvent.owner_user_id == user_id,
                ContentViewEvent.viewed_at >= window_start,
                ContentViewEvent.viewed_at <= anchor,
            )
        )
        or 0
    )


def _maybe_unlock_profile(db: Session, user_id: int, at: datetime | None = None) -> MonetizationProfile:
    profile = _get_or_create_profile(db, user_id)
    if profile.monetization_unlocked_at is None and _rolling_views_60d(db, user_id, at) >= MONETIZATION_THRESHOLD_VIEWS:
        profile.monetization_unlocked_at = _normalize_dt(at)
        profile.updated_at = _now()
        db.add(profile)
        db.flush()
    return profile


def _resolve_content_owner_and_video(db: Session, content_type: str, content_id: int) -> tuple[int | None, bool]:
    if content_type == "post":
        post = db.get(Post, content_id)
        if post is None or post.status != "published":
            return None, False
        has_video = bool(post.video_url) or bool(post.video_style)
        return (int(post.author_user_id) if post.author_user_id else None), has_video

    if content_type == "short":
        short = db.get(Short, content_id)
        if short is None or short.status != "published":
            return None, False
        return (int(short.author_user_id) if short.author_user_id else None), True

    if content_type == "comic":
        # Pipeline comics currently do not have a creator owner. They can be tracked
        # later if comics become user-owned, but they do not unlock/pay today.
        comic = db.get(Comic, content_id)
        if comic is None:
            return None, False
        return None, False

    return None, False


def _to_revenue_out(event: AdRevenueEvent) -> AdRevenueOut:
    return AdRevenueOut(
        id=int(event.id),
        content_type=event.content_type,  # type: ignore[arg-type]
        content_id=int(event.content_id),
        owner_user_id=int(event.owner_user_id),
        gross_revenue_cents=int(event.gross_revenue_cents),
        creator_share_cents=int(event.creator_share_cents),
        gist_share_cents=int(event.gist_share_cents),
        eligible_at_event=bool(event.eligible_at_event),
        is_video_content=bool(event.is_video_content),
        occurred_at=event.occurred_at,
    )


def _to_withdrawal_out(item: WithdrawalRequest) -> WithdrawalRequestOut:
    return WithdrawalRequestOut(
        id=int(item.id),
        amount_cents=int(item.amount_cents),
        status=item.status,
        payout_method=item.payout_method,
        payout_note=item.payout_note,
        requested_at=item.requested_at,
        updated_at=item.updated_at,
    )


def _assert_withdrawal_transition(current_status: str, new_status: str) -> None:
    terminal = {"paid", "rejected", "cancelled"}
    if current_status in terminal and current_status != new_status:
        raise HTTPException(status_code=400, detail=f"Withdrawal already in terminal state: {current_status}")

    if new_status == "approved" and current_status not in {"pending", "cancelled"}:
        raise HTTPException(
            status_code=400,
            detail="Only pending or cancelled withdrawals can be approved",
        )
    if new_status == "paid" and current_status not in {"pending", "approved"}:
        raise HTTPException(
            status_code=400,
            detail="Only pending or approved withdrawals can be marked as paid",
        )
    if new_status in {"rejected", "cancelled"} and current_status not in {"pending", "approved"}:
        raise HTTPException(
            status_code=400,
            detail="Only pending or approved withdrawals can be rejected or cancelled",
        )


def _assert_revenue_ingest_allowed(admin_secret: str | None) -> None:
    expected = get_settings().monetization_admin_secret.strip()
    if expected and admin_secret == expected:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Revenue ingestion is restricted")


@router.get("/me", response_model=MonetizationSummaryOut)
def monetization_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MonetizationSummaryOut:
    user_id = int(current_user.id)
    profile = _maybe_unlock_profile(db, user_id)
    rolling_views = _rolling_views_60d(db, user_id)
    pending_withdrawal_cents = int(
        db.scalar(
            select(func.coalesce(func.sum(WithdrawalRequest.amount_cents), 0)).where(
                WithdrawalRequest.user_id == user_id,
                WithdrawalRequest.status.in_(["pending", "approved"]),
            )
        )
        or 0
    )
    revenue_events = db.execute(
        select(AdRevenueEvent)
        .where(AdRevenueEvent.owner_user_id == user_id)
        .order_by(AdRevenueEvent.occurred_at.desc(), AdRevenueEvent.id.desc())
        .limit(10)
    ).scalars().all()
    withdrawals = db.execute(
        select(WithdrawalRequest)
        .where(WithdrawalRequest.user_id == user_id)
        .order_by(WithdrawalRequest.requested_at.desc(), WithdrawalRequest.id.desc())
        .limit(10)
    ).scalars().all()

    db.commit()
    return MonetizationSummaryOut(
        user_id=user_id,
        rolling_views_60d=rolling_views,
        monetization_unlocked=profile.monetization_unlocked_at is not None,
        monetization_unlocked_at=profile.monetization_unlocked_at,
        wallet_balance_cents=int(profile.wallet_balance_cents),
        total_earned_cents=int(profile.total_earned_cents),
        total_withdrawn_cents=int(profile.total_withdrawn_cents),
        pending_withdrawal_cents=pending_withdrawal_cents,
        recent_revenue_events=[_to_revenue_out(event) for event in revenue_events],
        withdrawals=[_to_withdrawal_out(item) for item in withdrawals],
    )


@router.post("/views", response_model=ContentViewsOut)
def record_content_views(
    payload: ContentViewsIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContentViewsOut:
    viewer_user_id = int(current_user.id)
    owner_ids: set[int] = set()
    recorded_count = 0

    for item in payload.views:
        owner_user_id, is_video = _resolve_content_owner_and_video(db, item.content_type, item.content_id)
        if owner_user_id is None:
            continue
        if owner_user_id == viewer_user_id:
            continue
        if not is_video:
            continue
        viewed_at = _normalize_dt(item.viewed_at)
        db.add(
            ContentViewEvent(
                content_type=item.content_type,
                content_id=item.content_id,
                owner_user_id=owner_user_id,
                viewer_user_id=viewer_user_id,
                viewed_at=viewed_at,
                source=item.source,
                session_key=item.session_key,
            )
        )
        owner_ids.add(owner_user_id)
        recorded_count += 1

    for owner_id in owner_ids:
        _maybe_unlock_profile(db, owner_id)

    current_profile = _maybe_unlock_profile(db, viewer_user_id)
    rolling_views = _rolling_views_60d(db, viewer_user_id)
    db.commit()
    return ContentViewsOut(
        recorded_count=recorded_count,
        rolling_views_60d=rolling_views,
        monetization_unlocked=current_profile.monetization_unlocked_at is not None,
        monetization_unlocked_at=current_profile.monetization_unlocked_at,
    )


@router.post("/revenue-events", response_model=AdRevenueOut)
def ingest_revenue_event(
    payload: AdRevenueIn,
    admin_secret: str | None = Header(default=None, alias="X-Monetization-Admin-Secret"),
    db: Session = Depends(get_db),
) -> AdRevenueOut:
    _assert_revenue_ingest_allowed(admin_secret)
    owner_user_id, is_video_content = _resolve_content_owner_and_video(db, payload.content_type, payload.content_id)
    if owner_user_id is None:
        raise HTTPException(status_code=404, detail="Owned content not found")

    occurred_at = _normalize_dt(payload.occurred_at)
    profile = _maybe_unlock_profile(db, owner_user_id, occurred_at)
    eligible_at_event = bool(
        is_video_content
        and profile.monetization_unlocked_at is not None
        and profile.monetization_unlocked_at <= occurred_at
    )
    creator_share_cents = (payload.gross_revenue_cents * CREATOR_REVENUE_SHARE_PERCENT) // 100 if eligible_at_event else 0
    gist_share_cents = payload.gross_revenue_cents - creator_share_cents

    event = AdRevenueEvent(
        content_type=payload.content_type,
        content_id=payload.content_id,
        owner_user_id=owner_user_id,
        gross_revenue_cents=payload.gross_revenue_cents,
        creator_share_cents=creator_share_cents,
        gist_share_cents=gist_share_cents,
        eligible_at_event=eligible_at_event,
        is_video_content=is_video_content,
        revenue_source=payload.revenue_source,
        external_event_id=payload.external_event_id,
        occurred_at=occurred_at,
    )
    db.add(event)

    if creator_share_cents > 0:
        profile.wallet_balance_cents += creator_share_cents
        profile.total_earned_cents += creator_share_cents
        profile.updated_at = _now()
        db.add(profile)

    db.commit()
    db.refresh(event)
    return _to_revenue_out(event)


@router.post("/withdrawals", response_model=WithdrawalRequestOut, status_code=201)
def request_withdrawal(
    payload: WithdrawalRequestIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WithdrawalRequestOut:
    user_id = int(current_user.id)
    profile = _get_or_create_profile(db, user_id)
    if profile.wallet_balance_cents < PAYOUT_THRESHOLD_CENTS:
        raise HTTPException(status_code=400, detail="Wallet balance must reach $50.00 before withdrawal")

    amount_cents = payload.amount_cents or int(profile.wallet_balance_cents)
    if amount_cents < PAYOUT_THRESHOLD_CENTS:
        raise HTTPException(status_code=400, detail="Withdrawal amount must be at least $50.00")
    if amount_cents > profile.wallet_balance_cents:
        raise HTTPException(status_code=400, detail="Withdrawal amount exceeds wallet balance")

    profile.wallet_balance_cents -= amount_cents
    profile.updated_at = _now()
    withdrawal = WithdrawalRequest(
        user_id=user_id,
        amount_cents=amount_cents,
        status="pending",
        payout_method=payload.payout_method,
        payout_note=payload.payout_note,
    )
    db.add(profile)
    db.add(withdrawal)
    db.commit()
    db.refresh(withdrawal)
    return _to_withdrawal_out(withdrawal)


@router.patch("/admin/withdrawals/{withdrawal_id}", response_model=WithdrawalRequestOut)
def moderate_withdrawal(
    withdrawal_id: int,
    payload: WithdrawalAdminUpdateIn,
    admin_secret: str | None = Header(default=None, alias="X-Monetization-Admin-Secret"),
    db: Session = Depends(get_db),
) -> WithdrawalRequestOut:
    _assert_revenue_ingest_allowed(admin_secret)
    if withdrawal_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid withdrawal id")
    if payload.status not in {"approved", "paid", "rejected", "cancelled"}:
        raise HTTPException(status_code=400, detail="Unsupported withdrawal status")

    withdrawal = db.get(WithdrawalRequest, withdrawal_id)
    if withdrawal is None:
        raise HTTPException(status_code=404, detail="Withdrawal request not found")

    if payload.payout_method is not None:
        withdrawal.payout_method = payload.payout_method
    if payload.payout_note is not None:
        withdrawal.payout_note = payload.payout_note

    _assert_withdrawal_transition(withdrawal.status, payload.status)
    if payload.status == "approved":
        withdrawal.status = "approved"
    elif payload.status == "paid":
        if withdrawal.status == "paid":
            raise HTTPException(status_code=400, detail="Withdrawal already marked as paid")
        # Move funds from pending wallet hold to paid history.
        profile = _get_or_create_profile(db, withdrawal.user_id)
        profile.total_withdrawn_cents += withdrawal.amount_cents
        withdrawal.status = "paid"
    elif payload.status in {"rejected", "cancelled"}:
        if withdrawal.status != payload.status:
            # Refund the reserved balance if not already returned.
            profile = _get_or_create_profile(db, withdrawal.user_id)
            profile.wallet_balance_cents += withdrawal.amount_cents
            withdrawal.status = payload.status
    db.add(withdrawal)
    db.commit()
    db.refresh(withdrawal)
    return _to_withdrawal_out(withdrawal)
