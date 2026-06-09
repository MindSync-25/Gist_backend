from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_optional, get_current_user
from app.core.database import get_db
from app.core.invites import build_invite_share_url, create_invite_link, get_invite_dashboard, resolve_invite_link
from app.models.user import User
from app.schemas.invite import InviteCreateIn, InviteDashboardOut, InviteLinkOut, InviteResolveIn, InviteResolveOut

router = APIRouter(prefix="/invites", tags=["invites"])


@router.post("", response_model=InviteLinkOut)
def create_invite(
    payload: InviteCreateIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InviteLinkOut:
    try:
        row = create_invite_link(
            db,
            inviter_user_id=int(current_user.id),
            invite_type=payload.invite_type,
            channel=payload.channel,
            target_entity_type=payload.target_entity_type,
            target_entity_id=payload.target_entity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    return InviteLinkOut(
        **row,
        share_url=build_invite_share_url(str(row["token"])),
        signups_count=0,
        activations_count=0,
    )


@router.post("/resolve", response_model=InviteResolveOut)
def resolve_invite(
    payload: InviteResolveIn,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> InviteResolveOut:
    row = resolve_invite_link(
        db,
        token=payload.token,
        actor_user_id=int(current_user.id) if current_user is not None else None,
        record_open=True,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    db.commit()
    return InviteResolveOut(**row, share_url=build_invite_share_url(str(row["token"])))


@router.get("/me", response_model=InviteDashboardOut)
def get_my_invites(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InviteDashboardOut:
    dashboard = get_invite_dashboard(db, inviter_user_id=int(current_user.id))
    return InviteDashboardOut(**dashboard)