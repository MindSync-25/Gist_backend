import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from jose import jwt

from app.core.config import get_settings


@dataclass
class SocialIdentity:
    provider: str
    provider_sub: str
    email: str
    email_verified: bool
    display_name: str | None = None


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def verify_google_id_token(id_token: str) -> SocialIdentity:
    settings = get_settings()
    qs = urllib.parse.urlencode({"id_token": id_token})
    data = _http_get_json(f"https://oauth2.googleapis.com/tokeninfo?{qs}")

    aud = str(data.get("aud", ""))
    if settings.google_oauth_client_id and aud != settings.google_oauth_client_id:
        raise ValueError("Google token audience mismatch")

    email = str(data.get("email", "")).strip().lower()
    sub = str(data.get("sub", "")).strip()
    if not email or not sub:
        raise ValueError("Invalid Google token payload")

    verified = str(data.get("email_verified", "false")).lower() == "true"
    return SocialIdentity(
        provider="google",
        provider_sub=sub,
        email=email,
        email_verified=verified,
        display_name=(data.get("name") or None),
    )


def verify_apple_id_token(id_token: str, fallback_email: str | None = None) -> SocialIdentity:
    settings = get_settings()
    if not settings.apple_oauth_client_id:
        raise ValueError("APPLE_OAUTH_CLIENT_ID is not configured")

    unverified_header = jwt.get_unverified_header(id_token)
    key_id = unverified_header.get("kid")
    jwks = _http_get_json("https://appleid.apple.com/auth/keys")
    keys = jwks.get("keys", [])
    key = next((k for k in keys if k.get("kid") == key_id), None)
    if not key:
        raise ValueError("Apple signing key not found")

    payload = jwt.decode(
        id_token,
        key,
        algorithms=["RS256"],
        audience=settings.apple_oauth_client_id,
        issuer="https://appleid.apple.com",
    )

    sub = str(payload.get("sub", "")).strip()
    email = str(payload.get("email") or fallback_email or "").strip().lower()
    if not sub or not email:
        raise ValueError("Apple token is missing required claims")

    email_verified = str(payload.get("email_verified", "false")).lower() == "true"
    return SocialIdentity(
        provider="apple",
        provider_sub=sub,
        email=email,
        email_verified=email_verified,
    )


def verify_social_id_token(provider: str, id_token: str, fallback_email: str | None = None) -> SocialIdentity:
    normalized = provider.strip().lower()
    if normalized == "google":
        return verify_google_id_token(id_token)
    if normalized == "apple":
        return verify_apple_id_token(id_token, fallback_email=fallback_email)
    raise ValueError("Unsupported social provider")
