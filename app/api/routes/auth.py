import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.avatar_signing import build_avatar_display_url, extract_managed_user_upload_key
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    AuthTokenOut,
    AuthUserOut,
    LogoutIn,
    LogoutOut,
    ProfileUpdateIn,
    RefreshIn,
    SignInIn,
    SignUpIn,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _s3_client():
    import boto3

    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.Session(**kwargs).client("s3", region_name=settings.aws_region)


def _extract_managed_avatar_key(url: str | None) -> str | None:
    return extract_managed_user_upload_key(url)


def _to_auth_user_out(user: User) -> AuthUserOut:
    avatar_display_url, avatar_display_expires_at = build_avatar_display_url(user.avatar_url)
    base = AuthUserOut.model_validate(user)
    return base.model_copy(
        update={
            "avatar_display_url": avatar_display_url,
            "avatar_display_expires_at": avatar_display_expires_at,
        }
    )


def _delete_previous_avatar_if_needed(previous_url: str | None, current_url: str | None) -> None:
    previous_key = _extract_managed_avatar_key(previous_url)
    if not previous_key:
        return

    current_key = _extract_managed_avatar_key(current_url)
    if current_key == previous_key:
        return

    settings = get_settings()
    try:
        s3 = _s3_client()
        s3.delete_object(Bucket=settings.s3_bucket_name, Key=previous_key)
    except Exception as exc:
        logger.warning("Failed to delete previous avatar object %s: %s", previous_key, exc)


def _build_auth_tokens(user: User) -> AuthTokenOut:
    settings = get_settings()
    return AuthTokenOut(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
        access_expires_in_seconds=settings.jwt_access_token_expire_minutes * 60,
        refresh_expires_in_seconds=settings.jwt_refresh_token_expire_minutes * 60,
        user=_to_auth_user_out(user),
    )


@router.post("/sign-up", response_model=AuthTokenOut)
def sign_up(payload: SignUpIn, db: Session = Depends(get_db)) -> AuthTokenOut:
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format",
        )

    existing = db.execute(
        select(User).where(
            or_(
                User.email == email,
                User.username == payload.username,
            )
        )
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email or username already exists",
        )

    user = User(
        username=payload.username.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return _build_auth_tokens(user)


@router.post("/sign-in", response_model=AuthTokenOut)
def sign_in(payload: SignInIn, db: Session = Depends(get_db)) -> AuthTokenOut:
    login = payload.login.strip().lower()

    user = db.execute(
        select(User).where(
            or_(
                User.email == login,
                User.username == payload.login.strip(),
            )
        )
    ).scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    user.last_login_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)

    return _build_auth_tokens(user)


@router.post("/refresh", response_model=AuthTokenOut)
def refresh(payload: RefreshIn, db: Session = Depends(get_db)) -> AuthTokenOut:
    subject = decode_refresh_token(payload.refresh_token)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    try:
        user_id = int(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    return _build_auth_tokens(user)


@router.post("/logout", response_model=LogoutOut)
def logout(_: LogoutIn | None = None, _current_user: User = Depends(get_current_user)) -> LogoutOut:
    # Tokens are stateless JWTs for now; frontend should clear local session.
    return LogoutOut(success=True)


@router.get("/me", response_model=AuthUserOut)
def me(current_user: User = Depends(get_current_user)) -> AuthUserOut:
    return _to_auth_user_out(current_user)


@router.patch("/me", response_model=AuthUserOut)
def update_me(
    payload: ProfileUpdateIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthUserOut:
    updates = payload.model_dump(exclude_unset=True)
    previous_avatar_url = current_user.avatar_url
    avatar_changed = False

    if "email" in updates:
        email = updates["email"].strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format",
            )

        existing = db.execute(
            select(User).where(
                User.email == email,
                User.id != current_user.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already exists",
            )

        current_user.email = email

    if "username" in updates:
        username = updates["username"].strip()
        if len(username) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username must be at least 3 characters",
            )

        existing = db.execute(
            select(User).where(
                User.username == username,
                User.id != current_user.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already exists",
            )

        current_user.username = username

    if "display_name" in updates:
        display_name = updates["display_name"].strip()
        if len(display_name) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Display name must be at least 2 characters",
            )
        current_user.display_name = display_name

    if "bio" in updates:
        bio = updates["bio"]
        if bio is None:
            current_user.bio = None
        else:
            normalized_bio = bio.strip()
            current_user.bio = normalized_bio or None

    if "location" in updates:
        location = updates["location"]
        if location is None:
            current_user.location = None
        else:
            normalized_location = location.strip()
            current_user.location = normalized_location or None

    if "avatar_url" in updates:
        avatar_url = updates["avatar_url"]
        if avatar_url is None:
            normalized_avatar_url = None
        else:
            normalized_avatar_url = avatar_url.strip() or None

        avatar_changed = normalized_avatar_url != (previous_avatar_url.strip() if isinstance(previous_avatar_url, str) else previous_avatar_url)
        current_user.avatar_url = normalized_avatar_url

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    if avatar_changed:
        _delete_previous_avatar_if_needed(previous_avatar_url, current_user.avatar_url)

    return _to_auth_user_out(current_user)
