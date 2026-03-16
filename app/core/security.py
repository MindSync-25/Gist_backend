from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


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
