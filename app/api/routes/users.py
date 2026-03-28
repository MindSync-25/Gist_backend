from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.avatar_signing import build_avatar_display_url
from app.core.database import get_db
from app.core.notifications import create_notification, send_expo_push, send_fcm_push
from app.api.deps import get_current_user
from app.models.follow import Follow
from app.models.user import User
from app.schemas.user import FollowOut, PublicUserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[PublicUserOut])
def list_users(
    q: str = Query(default=""),
    viewer_user_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(User).where(User.is_active.is_(True))

    if q.strip():
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(User.username).like(needle)
            | func.lower(User.display_name).like(needle)
        )

    rows = db.execute(
        stmt
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return [_build_public_user_out(u, db, viewer_user_id) for u in rows]


def _build_public_user_out(
    user: User,
    db: Session,
    viewer_user_id: int | None = None,
) -> PublicUserOut:
    followers_count = db.scalar(
        select(func.count()).select_from(Follow).where(Follow.followed_user_id == user.id)
    ) or 0
    following_count = db.scalar(
        select(func.count()).select_from(Follow).where(Follow.follower_user_id == user.id)
    ) or 0

    is_following = False
    if viewer_user_id and viewer_user_id != user.id:
        is_following = (
            db.get(Follow, (viewer_user_id, user.id)) is not None
        )

    avatar_display_url, avatar_display_expires_at = build_avatar_display_url(user.avatar_url)

    return PublicUserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        location=user.location,
        avatar_url=user.avatar_url,
        avatar_display_url=avatar_display_url,
        avatar_display_expires_at=avatar_display_expires_at,
        followers_count=followers_count,
        following_count=following_count,
        is_following=is_following,
    )


@router.get("/{user_id}", response_model=PublicUserOut)
def get_user_profile(
    user_id: int,
    viewer_user_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    return _build_public_user_out(user, db, viewer_user_id)


@router.post("/{user_id}/follow", response_model=FollowOut)
def toggle_follow(
    user_id: int,
    follower_user_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
):
    """Toggle follow/unfollow. Returns current following state."""
    if follower_user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    target = db.get(User, user_id)
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    follower = db.get(User, follower_user_id)
    if not follower or not follower.is_active:
        raise HTTPException(status_code=404, detail="Follower user not found")

    existing = db.get(Follow, (follower_user_id, user_id))
    if existing:
        db.delete(existing)
        db.commit()
        return FollowOut(follower_user_id=follower_user_id, followed_user_id=user_id, following=False)

    follow = Follow(follower_user_id=follower_user_id, followed_user_id=user_id)
    db.add(follow)
    try:
        create_notification(
            db,
            recipient_user_id=user_id,
            actor_user_id=follower_user_id,
            notification_type="follow",
            entity_type="user",
            entity_id=user_id,
            payload={
                "kind": "new_follower",
                "follower_user_id": int(follower_user_id),
                "followed_user_id": int(user_id),
            },
        )
    except Exception:
        pass
    db.commit()
    return FollowOut(follower_user_id=follower_user_id, followed_user_id=user_id, following=True)


@router.get("/{user_id}/followers", response_model=list[PublicUserOut])
def list_followers(
    user_id: int,
    viewer_user_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    rows = db.execute(
        select(User)
        .join(Follow, Follow.follower_user_id == User.id)
        .where(Follow.followed_user_id == user_id, User.is_active.is_(True))
        .order_by(Follow.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return [_build_public_user_out(u, db, viewer_user_id) for u in rows]


@router.get("/{user_id}/following", response_model=list[PublicUserOut])
def list_following(
    user_id: int,
    viewer_user_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    rows = db.execute(
        select(User)
        .join(Follow, Follow.followed_user_id == User.id)
        .where(Follow.follower_user_id == user_id, User.is_active.is_(True))
        .order_by(Follow.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return [_build_public_user_out(u, db, viewer_user_id) for u in rows]


class PushTokenIn(BaseModel):
    token: str
    provider: Literal["expo", "fcm"] = "expo"

    @field_validator("token")
    @classmethod
    def validate_non_empty_token(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Token is required")
        return v

    @model_validator(mode="after")
    def validate_provider_token_pair(self):
        token = self.token.strip()
        if self.provider == "expo":
            if not (token.startswith("ExponentPushToken[") or token.startswith("ExpoPushToken[")):
                raise ValueError("Must be a valid Expo push token")
        elif self.provider == "fcm":
            if len(token) < 20:
                raise ValueError("Must be a valid FCM token")
        return self


class PushTestIn(BaseModel):
    body: str = "This is a test push from Gist"


@router.put("/me/push-token", status_code=204)
def upsert_push_token(
    body: PushTokenIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Save or update the caller's push token (FCM or Expo)."""
    if body.provider == "fcm":
        current_user.fcm_push_token = body.token
        # Keep Expo token optional as fallback during migration.
    else:
        current_user.expo_push_token = body.token
    db.commit()


@router.delete("/me/push-token", status_code=204)
def delete_push_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Clear push tokens on logout."""
    current_user.expo_push_token = None
    current_user.fcm_push_token = None
    db.commit()


@router.post("/me/push-token/test")
def test_push_token_delivery(
    body: PushTestIn,
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Send a direct test push to the currently saved token for this user."""
    fcm_token = (current_user.fcm_push_token or "").strip()
    expo_token = (current_user.expo_push_token or "").strip()
    token = fcm_token or expo_token
    if not token:
        raise HTTPException(status_code=400, detail="No push token saved for this user")

    provider = "fcm" if fcm_token else "expo"
    if provider == "fcm":
        result = send_fcm_push(
            token,
            notification_type="system",
            actor_display_name=current_user.display_name,
            payload={"message": body.body},
        )
    else:
        result = send_expo_push(
            token,
            notification_type="system",
            actor_display_name=current_user.display_name,
            payload={"message": body.body},
        )
    return {
        "ok": bool(result.get("ok")),
        "provider": provider,
        "token_prefix": token[:20],
        "result": result,
    }
