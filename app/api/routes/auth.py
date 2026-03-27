import logging
import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.avatar_signing import build_avatar_display_url, extract_managed_user_upload_key
from app.core.config import get_settings
from app.core.database import get_db
from app.core.emailer import send_otp_email
from app.core.security import (
    create_access_token,
    create_otp_code,
    create_refresh_token,
    decode_refresh_token,
    hash_otp,
    hash_password,
    verify_otp,
    verify_password,
)
from app.core.social_auth import exchange_google_auth_code, verify_social_id_token
from app.models.user import User
from app.schemas.auth import (
    AuthTokenOut,
    AuthUserOut,
    ChangePasswordIn,
    ForgotPasswordRequestOtpIn,
    ForgotPasswordResetIn,
    LogoutIn,
    LogoutOut,
    OtpAckOut,
    ProfileUpdateIn,
    RefreshIn,
    SignInIn,
    SignUpIn,
    SignUpRequestOtpIn,
    SignUpVerifyOtpIn,
    SocialConnectIn,
    SocialSignInIn,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


_USERNAME_ALLOWED = re.compile(r"^[a-zA-Z0-9._]{3,50}$")


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
            "google_connected": bool(user.google_sub),
            "apple_connected": bool(user.apple_sub),
        }
    )


def _validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or "." not in normalized.split("@")[-1]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format",
        )
    return normalized


def _validate_username(username: str) -> str:
    normalized = username.strip()
    if not _USERNAME_ALLOWED.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be 3-50 chars and only include letters, numbers, dot, underscore",
        )
    return normalized


def _ensure_unique_email_or_username(db: Session, email: str, username: str, exclude_user_id: int | None = None) -> None:
    stmt = select(User).where(
        or_(
            User.email == email,
            User.username == username,
        )
    )
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)

    existing = db.execute(stmt).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email or username already exists",
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


def _set_social_sub(user: User, provider: str, provider_sub: str) -> None:
    if provider == "google":
        user.google_sub = provider_sub
    elif provider == "apple":
        user.apple_sub = provider_sub


def _social_sub_column(provider: str):
    return User.google_sub if provider == "google" else User.apple_sub


def _safe_username_from_email(email: str) -> str:
    local = email.split("@", 1)[0].lower()
    local = re.sub(r"[^a-z0-9._]", "", local)
    local = local[:40] if local else "user"
    return local


def _unique_username(db: Session, base: str) -> str:
    username = base if len(base) >= 3 else f"{base}user"
    username = username[:50]

    for _ in range(20):
        exists = db.execute(select(User.id).where(User.username == username)).scalar_one_or_none()
        if exists is None:
            return username
        suffix = secrets.token_hex(2)
        prefix = username[: max(3, 50 - len(suffix) - 1)]
        username = f"{prefix}_{suffix}"

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not generate unique username")


@router.get("/check-username")
def check_username(username: str = Query(min_length=3, max_length=50), db: Session = Depends(get_db)) -> dict[str, object]:
    normalized = _validate_username(username)
    existing = db.execute(select(User.id).where(User.username == normalized)).scalar_one_or_none()
    return {"username": normalized, "available": existing is None}


@router.post("/sign-up/request-otp", response_model=OtpAckOut)
def sign_up_request_otp(payload: SignUpRequestOtpIn, db: Session = Depends(get_db)) -> OtpAckOut:
    settings = get_settings()
    email = _validate_email(payload.email)
    username = _validate_username(payload.username)
    _ensure_unique_email_or_username(db, email, username)

    otp = create_otp_code()
    otp_hash = hash_otp(email, otp)
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.otp_expire_minutes)

    db.execute(
        text(
            """
            INSERT INTO auth_signup_otps
                (email, username, display_name, date_of_birth, password_hash, otp_hash, expires_at)
            VALUES
                (:email, :username, :display_name, :date_of_birth, :password_hash, :otp_hash, :expires_at)
            """
        ),
        {
            "email": email,
            "username": username,
            "display_name": payload.display_name.strip(),
            "date_of_birth": payload.date_of_birth,
            "password_hash": hash_password(payload.password),
            "otp_hash": otp_hash,
            "expires_at": expires_at,
        },
    )
    db.commit()

    send_otp_email(
        email=email,
        otp=otp,
        subject="Gist sign-up verification OTP",
        intro="Use this OTP to verify your email and complete your Gist registration.",
    )
    return OtpAckOut(success=True, message="OTP sent to your email")


@router.post("/sign-up/verify-otp", response_model=AuthTokenOut)
def sign_up_verify_otp(payload: SignUpVerifyOtpIn, db: Session = Depends(get_db)) -> AuthTokenOut:
    email = _validate_email(payload.email)
    now = datetime.now(UTC)

    record = db.execute(
        text(
            """
            SELECT id, email, username, display_name, date_of_birth, password_hash, otp_hash
            FROM auth_signup_otps
            WHERE email = :email
              AND consumed_at IS NULL
              AND expires_at > :now
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"email": email, "now": now},
    ).mappings().first()

    if record is None or not verify_otp(email, payload.otp.strip(), str(record["otp_hash"])):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OTP")

    _ensure_unique_email_or_username(db, email, str(record["username"]))

    user = User(
        username=str(record["username"]),
        email=email,
        password_hash=str(record["password_hash"]),
        display_name=str(record["display_name"]),
        date_of_birth=record["date_of_birth"],
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()

    db.execute(
        text("UPDATE auth_signup_otps SET consumed_at = :now WHERE id = :id"),
        {"now": now, "id": int(record["id"])},
    )
    db.commit()
    db.refresh(user)
    return _build_auth_tokens(user)


@router.post("/sign-up", response_model=AuthTokenOut)
def sign_up(payload: SignUpIn, db: Session = Depends(get_db)) -> AuthTokenOut:
    email = _validate_email(payload.email)
    username = _validate_username(payload.username)
    _ensure_unique_email_or_username(db, email, username)

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
        date_of_birth=payload.date_of_birth,
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


@router.post("/social/sign-in", response_model=AuthTokenOut)
def social_sign_in(payload: SocialSignInIn, db: Session = Depends(get_db)) -> AuthTokenOut:
    try:
        if payload.code:
            # Android authorization code flow
            if not payload.redirect_uri:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="redirect_uri is required for code flow")
            identity = exchange_google_auth_code(
                code=payload.code,
                redirect_uri=payload.redirect_uri,
                code_verifier=payload.code_verifier,
            )
        elif payload.id_token:
            identity = verify_social_id_token(payload.provider, payload.id_token, fallback_email=payload.email)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either id_token or code is required")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Social sign-in failed: {exc}") from exc

    sub_column = _social_sub_column(identity.provider)
    user = db.execute(select(User).where(sub_column == identity.provider_sub)).scalar_one_or_none()

    if user is None:
        user = db.execute(select(User).where(User.email == identity.email)).scalar_one_or_none()

    if user is None:
        display_name = (payload.display_name or identity.display_name or identity.email.split("@", 1)[0]).strip()
        username = _unique_username(db, _safe_username_from_email(identity.email))

        user = User(
            username=username,
            email=identity.email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=display_name[:80] if display_name else username,
            is_active=True,
            is_verified=identity.email_verified,
        )
        _set_social_sub(user, identity.provider, identity.provider_sub)
        db.add(user)
    else:
        _set_social_sub(user, identity.provider, identity.provider_sub)
        if not user.is_verified and identity.email_verified:
            user.is_verified = True

    user.last_login_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)

    return _build_auth_tokens(user)


@router.post("/social/connect", response_model=AuthUserOut)
def social_connect(
    payload: SocialConnectIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthUserOut:
    try:
        identity = verify_social_id_token(payload.provider, payload.id_token, fallback_email=payload.email)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Social connect failed: {exc}") from exc

    if identity.email != current_user.email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Social account email does not match current user")

    sub_column = _social_sub_column(identity.provider)
    other = db.execute(select(User).where(sub_column == identity.provider_sub, User.id != current_user.id)).scalar_one_or_none()
    if other is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This social account is already connected to another user")

    _set_social_sub(current_user, identity.provider, identity.provider_sub)
    db.commit()
    db.refresh(current_user)
    return _to_auth_user_out(current_user)


@router.post("/forgot-password/request-otp", response_model=OtpAckOut)
def forgot_password_request_otp(payload: ForgotPasswordRequestOtpIn, db: Session = Depends(get_db)) -> OtpAckOut:
    settings = get_settings()
    email = _validate_email(payload.email)
    user = db.execute(select(User).where(User.email == email, User.is_active.is_(True))).scalar_one_or_none()

    if user is not None:
        otp = create_otp_code()
        expires_at = datetime.now(UTC) + timedelta(minutes=settings.otp_expire_minutes)

        db.execute(
            text(
                """
                INSERT INTO auth_password_reset_otps (user_id, email, otp_hash, expires_at)
                VALUES (:user_id, :email, :otp_hash, :expires_at)
                """
            ),
            {
                "user_id": user.id,
                "email": email,
                "otp_hash": hash_otp(email, otp),
                "expires_at": expires_at,
            },
        )
        db.commit()

        send_otp_email(
            email=email,
            otp=otp,
            subject="Gist password reset OTP",
            intro="Use this OTP to reset your Gist account password.",
        )

    return OtpAckOut(success=True, message="If the account exists, an OTP has been sent")


@router.post("/forgot-password/reset", response_model=OtpAckOut)
def forgot_password_reset(payload: ForgotPasswordResetIn, db: Session = Depends(get_db)) -> OtpAckOut:
    email = _validate_email(payload.email)
    now = datetime.now(UTC)

    record = db.execute(
        text(
            """
            SELECT id, user_id, otp_hash
            FROM auth_password_reset_otps
            WHERE email = :email
              AND consumed_at IS NULL
              AND expires_at > :now
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"email": email, "now": now},
    ).mappings().first()

    if record is None or not verify_otp(email, payload.otp.strip(), str(record["otp_hash"])):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OTP")

    user = db.get(User, int(record["user_id"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.password_hash = hash_password(payload.new_password)
    user.updated_at = datetime.now(UTC)

    db.execute(
        text("UPDATE auth_password_reset_otps SET consumed_at = :now WHERE id = :id"),
        {"now": now, "id": int(record["id"])},
    )
    db.commit()
    return OtpAckOut(success=True, message="Password reset successful")


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
        email = _validate_email(updates["email"])
        _ensure_unique_email_or_username(db, email, current_user.username, exclude_user_id=current_user.id)
        current_user.email = email

    if "username" in updates:
        username = _validate_username(updates["username"])
        _ensure_unique_email_or_username(db, current_user.email, username, exclude_user_id=current_user.id)
        current_user.username = username

    if "display_name" in updates:
        display_name = updates["display_name"].strip()
        if len(display_name) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Display name must be at least 2 characters",
            )
        current_user.display_name = display_name

    if "date_of_birth" in updates:
        current_user.date_of_birth = updates["date_of_birth"]

    if "bio" in updates:
        bio = updates["bio"]
        current_user.bio = (bio.strip() or None) if isinstance(bio, str) else None

    if "location" in updates:
        location = updates["location"]
        current_user.location = (location.strip() or None) if isinstance(location, str) else None

    if "language" in updates:
        language = updates["language"]
        current_user.language = (language.strip() or "en") if isinstance(language, str) else "en"

    if "avatar_url" in updates:
        avatar_url = updates["avatar_url"]
        normalized_avatar_url = (avatar_url.strip() or None) if isinstance(avatar_url, str) else None
        avatar_changed = normalized_avatar_url != (
            previous_avatar_url.strip() if isinstance(previous_avatar_url, str) else previous_avatar_url
        )
        current_user.avatar_url = normalized_avatar_url

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    if avatar_changed:
        _delete_previous_avatar_if_needed(previous_avatar_url, current_user.avatar_url)

    return _to_auth_user_out(current_user)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password",
        )

    current_user.password_hash = hash_password(payload.new_password)
    current_user.updated_at = datetime.now(UTC)
    db.commit()
    return {"message": "Password updated successfully"}
