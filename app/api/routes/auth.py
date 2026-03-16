from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import AuthTokenOut, AuthUserOut, LogoutIn, LogoutOut, RefreshIn, SignInIn, SignUpIn

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_auth_tokens(user: User) -> AuthTokenOut:
    return AuthTokenOut(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
        user=AuthUserOut.model_validate(user),
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
    return AuthUserOut.model_validate(current_user)
