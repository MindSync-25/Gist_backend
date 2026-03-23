import hmac
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _create_token(subject: str, token_type: str, expires_minutes: int) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    to_encode = {"sub": subject, "exp": expire, "type": token_type}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    expire_minutes = expires_minutes or settings.jwt_access_token_expire_minutes
    return _create_token(subject, "access", expire_minutes)


def create_refresh_token(subject: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    expire_minutes = expires_minutes or settings.jwt_refresh_token_expire_minutes
    return _create_token(subject, "refresh", expire_minutes)


def _decode_token(token: str) -> dict[str, object] | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if not isinstance(payload, dict):
            return None
        return payload
    except JWTError:
        return None


def decode_access_token(token: str) -> str | None:
    payload = _decode_token(token)
    if payload is None:
        return None

    token_type = payload.get("type")
    if token_type not in (None, "access"):
        return None

    sub = payload.get("sub")
    if not isinstance(sub, str):
        return None
    return sub


def decode_refresh_token(token: str) -> str | None:
    payload = _decode_token(token)
    if payload is None:
        return None

    if payload.get("type") != "refresh":
        return None

    sub = payload.get("sub")
    if not isinstance(sub, str):
        return None
    return sub


def create_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(identifier: str, otp: str) -> str:
    settings = get_settings()
    msg = f"{identifier.lower().strip()}:{otp}".encode("utf-8")
    return hmac.new(settings.jwt_secret.encode("utf-8"), msg, sha256).hexdigest()


def verify_otp(identifier: str, otp: str, otp_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(identifier, otp), otp_hash)
