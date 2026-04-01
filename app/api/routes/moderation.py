from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.comic_comment import ComicComment
from app.models.comment import Comment
from app.models.post import Post
from app.models.user import User
from app.models.user_block import UserBlock
from app.models.report import Report
from app.schemas.moderation import BlockOut, BlockedUserOut, ReportIn, ReportOut

router = APIRouter(tags=["moderation"])


def _validate_report_target_exists(db: Session, entity_type: str, entity_id: int) -> None:
    if entity_type == "user":
        user = db.get(User, entity_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=404, detail="Reported user not found")
        return

    if entity_type == "post":
        post = db.get(Post, entity_id)
        if post is None:
            raise HTTPException(status_code=404, detail="Reported post not found")
        return

    if entity_type == "comment":
        comment = db.get(Comment, entity_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Reported comment not found")
        return

    if entity_type == "comic_comment":
        comment = db.get(ComicComment, entity_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Reported comic comment not found")
        return

    raise HTTPException(status_code=400, detail="Unsupported report entity type")


# ---------------------------------------------------------------------------
# Block / Unblock
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/block", response_model=BlockOut)
def toggle_block(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Block or unblock a user. Returns the current blocked state."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")

    target = db.get(User, user_id)
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.get(UserBlock, (current_user.id, user_id))
    if existing:
        db.delete(existing)
        db.commit()
        return BlockOut(blocker_user_id=current_user.id, blocked_user_id=user_id, blocked=False)

    block = UserBlock(blocker_user_id=current_user.id, blocked_user_id=user_id)
    db.add(block)
    db.commit()
    return BlockOut(blocker_user_id=current_user.id, blocked_user_id=user_id, blocked=True)


@router.get("/users/me/blocked", response_model=list[BlockedUserOut])
def list_blocked_users(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return users that the current user has blocked."""
    rows = db.execute(
        select(UserBlock, User)
        .join(User, User.id == UserBlock.blocked_user_id)
        .where(UserBlock.blocker_user_id == current_user.id)
        .order_by(UserBlock.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return [
        BlockedUserOut(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            blocked_at=block.created_at,
        )
        for block, user in rows
    ]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@router.post("/reports", response_model=ReportOut, status_code=201)
def create_report(
    payload: ReportIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit a report against a post, comment, or user."""
    _validate_report_target_exists(db, payload.entity_type, payload.entity_id)

    # Prevent duplicate reports for the same entity by the same user
    existing = db.execute(
        select(Report).where(
            Report.reporter_user_id == current_user.id,
            Report.entity_type == payload.entity_type,
            Report.entity_id == payload.entity_id,
        )
    ).scalar_one_or_none()

    if existing:
        # Idempotent: return the already-submitted report rather than an error
        return existing

    report = Report(
        reporter_user_id=current_user.id,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        reason=payload.reason,
        detail=payload.detail,
        status="pending",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
