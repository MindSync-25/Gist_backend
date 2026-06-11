from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models.gist_coin import GistCoinTopUpRequest, GistCoinTransaction, GistCoinWallet, GistTipTransaction
from app.models.post import Post
from app.models.short import Short
from app.models.user import User
from app.schemas.gist_coin import (
    CoinGrantIn,
    CoinTopUpIn,
    GistCoinTransactionOut,
    GistCoinWalletOut,
    TopUpRequestAdminUpdateIn,
    TopUpRequestIn,
    TopUpRequestOut,
    TipCreateIn,
    TipSummaryOut,
    TipTransactionOut,
)

router = APIRouter(prefix="/gist-coins", tags=["gist-coins"])
CREATOR_TIP_SHARE_PERCENT = 90


def _get_or_create_wallet(db: Session, user_id: int, *, lock: bool = False) -> GistCoinWallet:
    stmt = select(GistCoinWallet).where(GistCoinWallet.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    wallet = db.execute(stmt).scalar_one_or_none()
    if wallet is None:
        wallet = GistCoinWallet(user_id=user_id)
        db.add(wallet)
        db.flush()
        if lock:
            wallet = db.execute(stmt).scalar_one()
    return wallet


def _to_wallet_out(wallet: GistCoinWallet) -> GistCoinWalletOut:
    return GistCoinWalletOut(
        user_id=int(wallet.user_id),
        balance_coins=int(wallet.balance_coins),
        total_received_coins=int(wallet.total_received_coins),
        total_spent_coins=int(wallet.total_spent_coins),
    )


def _to_transaction_out(item: GistCoinTransaction) -> GistCoinTransactionOut:
    return GistCoinTransactionOut(
        id=int(item.id),
        user_id=int(item.user_id),
        direction=item.direction,
        transaction_type=item.transaction_type,
        amount_coins=int(item.amount_coins),
        balance_after_coins=int(item.balance_after_coins),
        counterparty_user_id=int(item.counterparty_user_id) if item.counterparty_user_id else None,
        content_type=item.content_type,
        content_id=int(item.content_id) if item.content_id else None,
        reference_type=item.reference_type,
        reference_id=int(item.reference_id) if item.reference_id else None,
        note=item.note,
        created_at=item.created_at,
    )


def _resolve_tip_recipient(db: Session, content_type: str, content_id: int) -> int:
    if content_type == "post":
        post = db.get(Post, content_id)
        if post is None or post.status != "published":
            raise HTTPException(status_code=404, detail="Post not found")
        if post.is_secret:
            raise HTTPException(status_code=400, detail="Secret posts cannot receive tips")
        if not post.author_user_id:
            raise HTTPException(status_code=400, detail="This post cannot receive tips")
        return int(post.author_user_id)

    if content_type == "short":
        short = db.get(Short, content_id)
        if short is None or short.status != "published":
            raise HTTPException(status_code=404, detail="Pulse video not found")
        if not short.author_user_id:
            raise HTTPException(status_code=400, detail="This Pulse video cannot receive tips")
        return int(short.author_user_id)

    raise HTTPException(status_code=400, detail="Unsupported content type")


def _assert_coin_admin_allowed(admin_secret: str | None) -> None:
    expected = get_settings().monetization_admin_secret.strip()
    if expected and admin_secret == expected:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Coin administration is restricted")


def _to_topup_request_out(item: GistCoinTopUpRequest) -> TopUpRequestOut:
    return TopUpRequestOut(
        id=int(item.id),
        user_id=int(item.user_id),
        amount_coins=int(item.amount_coins),
        status=item.status,
        source=item.source,
        provider_reference_id=item.provider_reference_id,
        note=item.note,
        requested_at=item.requested_at,
        updated_at=item.updated_at,
    )


def _apply_approved_top_up(db: Session, top_up_request: GistCoinTopUpRequest) -> None:
    wallet = _get_or_create_wallet(db, int(top_up_request.user_id), lock=True)
    wallet.balance_coins += int(top_up_request.amount_coins)
    wallet.total_received_coins += int(top_up_request.amount_coins)
    db.add(wallet)
    db.add(
        GistCoinTransaction(
            user_id=int(top_up_request.user_id),
            direction="credit",
            transaction_type="purchase",
            amount_coins=int(top_up_request.amount_coins),
            balance_after_coins=int(wallet.balance_coins),
            reference_type="topup_request",
            reference_id=int(top_up_request.id),
            note=top_up_request.note,
        )
    )


@router.get("/me", response_model=GistCoinWalletOut)
def get_my_coin_wallet(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GistCoinWalletOut:
    wallet = _get_or_create_wallet(db, int(current_user.id))
    db.commit()
    return _to_wallet_out(wallet)


@router.get("/transactions", response_model=list[GistCoinTransactionOut])
def get_my_coin_transactions(
    limit: int = 30,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[GistCoinTransactionOut]:
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)
    rows = db.execute(
        select(GistCoinTransaction)
        .where(GistCoinTransaction.user_id == int(current_user.id))
        .order_by(GistCoinTransaction.created_at.desc(), GistCoinTransaction.id.desc())
        .offset(safe_offset)
        .limit(safe_limit)
    ).scalars().all()
    return [_to_transaction_out(item) for item in rows]


@router.post("/top-up-requests", response_model=TopUpRequestOut, status_code=201)
def create_top_up_request(
    payload: TopUpRequestIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TopUpRequestOut:
    user_id = int(current_user.id)

    existing = None
    if payload.provider_reference_id:
        existing = db.execute(
            select(GistCoinTopUpRequest)
            .where(
                GistCoinTopUpRequest.user_id == user_id,
                GistCoinTopUpRequest.provider_reference_id == payload.provider_reference_id,
                GistCoinTopUpRequest.status.in_(["pending", "approved"]),
            )
        ).scalar_one_or_none()
    if existing is not None:
        return _to_topup_request_out(existing)

    request_row = GistCoinTopUpRequest(
        user_id=user_id,
        amount_coins=payload.amount_coins,
        source=(payload.source or "app").strip()[:32] or "app",
        provider_reference_id=payload.provider_reference_id,
        note=payload.note,
    )
    db.add(request_row)
    db.commit()
    db.refresh(request_row)
    return _to_topup_request_out(request_row)


@router.get("/top-up-requests", response_model=list[TopUpRequestOut])
def list_my_top_up_requests(
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TopUpRequestOut]:
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)

    stmt = select(GistCoinTopUpRequest).where(GistCoinTopUpRequest.user_id == int(current_user.id))
    if status:
        stmt = stmt.where(GistCoinTopUpRequest.status == status)
    rows = db.execute(
        stmt.order_by(
            GistCoinTopUpRequest.requested_at.desc(),
            GistCoinTopUpRequest.id.desc(),
        )
        .offset(safe_offset)
        .limit(safe_limit)
    ).scalars().all()
    return [_to_topup_request_out(item) for item in rows]


@router.post("/tips", response_model=TipTransactionOut, status_code=201)
def create_tip(
    payload: TipCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TipTransactionOut:
    sender_user_id = int(current_user.id)
    recipient_user_id = _resolve_tip_recipient(db, payload.content_type, payload.content_id)
    if recipient_user_id == sender_user_id:
        raise HTTPException(status_code=400, detail="You cannot tip your own content")

    if sender_user_id < recipient_user_id:
        sender_wallet = _get_or_create_wallet(db, sender_user_id, lock=True)
        recipient_wallet = _get_or_create_wallet(db, recipient_user_id, lock=True)
    else:
        recipient_wallet = _get_or_create_wallet(db, recipient_user_id, lock=True)
        sender_wallet = _get_or_create_wallet(db, sender_user_id, lock=True)
    if sender_wallet.balance_coins < payload.amount_coins:
        raise HTTPException(status_code=400, detail="Not enough GIST Coins")

    creator_share = (payload.amount_coins * CREATOR_TIP_SHARE_PERCENT) // 100
    platform_fee = payload.amount_coins - creator_share

    sender_wallet.balance_coins -= payload.amount_coins
    sender_wallet.total_spent_coins += payload.amount_coins
    recipient_wallet.balance_coins += creator_share
    recipient_wallet.total_received_coins += creator_share

    tip = GistTipTransaction(
        sender_user_id=sender_user_id,
        recipient_user_id=recipient_user_id,
        content_type=payload.content_type,
        content_id=payload.content_id,
        amount_coins=payload.amount_coins,
        creator_share_coins=creator_share,
        platform_fee_coins=platform_fee,
        status="succeeded",
        message=payload.message.strip() if payload.message and payload.message.strip() else None,
    )
    db.add(tip)
    db.flush()

    sender_tx = GistCoinTransaction(
        user_id=sender_user_id,
        direction="debit",
        transaction_type="tip_sent",
        amount_coins=payload.amount_coins,
        balance_after_coins=int(sender_wallet.balance_coins),
        counterparty_user_id=recipient_user_id,
        content_type=payload.content_type,
        content_id=payload.content_id,
        reference_type="tip",
        reference_id=tip.id,
        note=tip.message,
    )
    db.add(sender_tx)

    if creator_share > 0:
        db.add(
            GistCoinTransaction(
                user_id=recipient_user_id,
                direction="credit",
                transaction_type="tip_received",
                amount_coins=creator_share,
                balance_after_coins=int(recipient_wallet.balance_coins),
                counterparty_user_id=sender_user_id,
                content_type=payload.content_type,
                content_id=payload.content_id,
                reference_type="tip",
                reference_id=tip.id,
                note=tip.message,
            )
        )

    db.add(sender_wallet)
    db.add(recipient_wallet)
    db.commit()
    db.refresh(tip)

    return TipTransactionOut(
        id=int(tip.id),
        sender_user_id=sender_user_id,
        recipient_user_id=recipient_user_id,
        content_type=tip.content_type,  # type: ignore[arg-type]
        content_id=int(tip.content_id),
        amount_coins=int(tip.amount_coins),
        creator_share_coins=int(tip.creator_share_coins),
        platform_fee_coins=int(tip.platform_fee_coins),
        status=tip.status,
        message=tip.message,
        created_at=tip.created_at,
        sender_balance_coins=int(sender_wallet.balance_coins),
    )


@router.get("/tips/{content_type}/{content_id}", response_model=TipSummaryOut)
def get_tip_summary(
    content_type: str,
    content_id: int,
    db: Session = Depends(get_db),
) -> TipSummaryOut:
    if content_type not in {"post", "short"}:
        raise HTTPException(status_code=400, detail="Unsupported content type")
    row = db.execute(
        select(
            func.count(GistTipTransaction.id),
            func.coalesce(func.sum(GistTipTransaction.amount_coins), 0),
            func.coalesce(func.sum(GistTipTransaction.creator_share_coins), 0),
        ).where(
            GistTipTransaction.content_type == content_type,
            GistTipTransaction.content_id == content_id,
            GistTipTransaction.status == "succeeded",
        )
    ).one()
    return TipSummaryOut(
        content_type=content_type,  # type: ignore[arg-type]
        content_id=content_id,
        tips_count=int(row[0] or 0),
        total_tip_coins=int(row[1] or 0),
        total_creator_share_coins=int(row[2] or 0),
    )


@router.post("/admin/grants", response_model=GistCoinWalletOut, status_code=201)
def grant_coins(
    payload: CoinGrantIn,
    admin_secret: str | None = Header(default=None, alias="X-Monetization-Admin-Secret"),
    db: Session = Depends(get_db),
) -> GistCoinWalletOut:
    _assert_coin_admin_allowed(admin_secret)
    user = db.get(User, payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    wallet = _get_or_create_wallet(db, payload.user_id, lock=True)
    wallet.balance_coins += payload.amount_coins
    wallet.total_received_coins += payload.amount_coins
    db.add(wallet)
    db.flush()
    db.add(
        GistCoinTransaction(
            user_id=payload.user_id,
            direction="credit",
            transaction_type="admin_grant",
            amount_coins=payload.amount_coins,
            balance_after_coins=int(wallet.balance_coins),
            note=payload.note,
        )
    )
    db.commit()
    db.refresh(wallet)
    return _to_wallet_out(wallet)


@router.post("/admin/top-ups", response_model=GistCoinWalletOut, status_code=201)
def record_top_up(
    payload: CoinTopUpIn,
    admin_secret: str | None = Header(default=None, alias="X-Monetization-Admin-Secret"),
    db: Session = Depends(get_db),
) -> GistCoinWalletOut:
    _assert_coin_admin_allowed(admin_secret)

    user = db.get(User, payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    existing_top_up = None
    if payload.provider_reference_id is not None:
        existing_top_up = db.execute(
            select(GistCoinTransaction)
            .where(
                GistCoinTransaction.user_id == payload.user_id,
                GistCoinTransaction.transaction_type == "purchase",
                GistCoinTransaction.reference_type == "topup",
                GistCoinTransaction.reference_id == payload.provider_reference_id,
            )
        ).scalar_one_or_none()

    if existing_top_up is not None:
        wallet = _get_or_create_wallet(db, payload.user_id, lock=True)
        return _to_wallet_out(wallet)

    wallet = _get_or_create_wallet(db, payload.user_id, lock=True)
    wallet.balance_coins += payload.amount_coins
    wallet.total_received_coins += payload.amount_coins
    db.add(wallet)
    db.flush()
    db.add(
        GistCoinTransaction(
            user_id=payload.user_id,
            direction="credit",
            transaction_type="purchase",
            amount_coins=payload.amount_coins,
            balance_after_coins=int(wallet.balance_coins),
            reference_type="topup",
            reference_id=payload.provider_reference_id,
            note=payload.note,
        )
    )
    db.commit()
    db.refresh(wallet)
    return _to_wallet_out(wallet)


@router.patch("/admin/top-up-requests/{request_id}", response_model=TopUpRequestOut)
def moderate_top_up_request(
    request_id: int,
    payload: TopUpRequestAdminUpdateIn,
    admin_secret: str | None = Header(default=None, alias="X-Monetization-Admin-Secret"),
    db: Session = Depends(get_db),
) -> TopUpRequestOut:
    _assert_coin_admin_allowed(admin_secret)
    if request_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid top-up request id")

    request_row = db.get(GistCoinTopUpRequest, request_id)
    if request_row is None:
        raise HTTPException(status_code=404, detail="Top-up request not found")
    if payload.provider_reference_id is not None:
        request_row.provider_reference_id = payload.provider_reference_id
    if payload.note is not None:
        request_row.note = payload.note

    if payload.status == "approved":
        if request_row.status != "pending":
            db.refresh(request_row)
            if request_row.status == "approved":
                return _to_topup_request_out(request_row)
            raise HTTPException(
                status_code=400,
                detail=f"Top-up request cannot be approved from status '{request_row.status}'",
            )
        _apply_approved_top_up(db, request_row)

    request_row.status = payload.status
    db.add(request_row)
    db.commit()
    db.refresh(request_row)
    return _to_topup_request_out(request_row)
