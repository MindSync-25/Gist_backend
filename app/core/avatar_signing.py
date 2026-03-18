from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import parse_qs, unquote, urlparse

from app.core.config import get_settings


@lru_cache
def _s3_client():
    import boto3

    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.Session(**kwargs).client("s3", region_name=settings.aws_region)


def _extract_object_key_from_s3_url(raw_url: str) -> str | None:
    settings = get_settings()
    parsed = urlparse(raw_url)
    host = parsed.netloc.lower()
    bucket = settings.s3_bucket_name.lower()

    if host in {f"{bucket}.s3.{settings.aws_region}.amazonaws.com", f"{bucket}.s3.amazonaws.com"}:
        return unquote(parsed.path.lstrip("/"))

    if host in {f"s3.{settings.aws_region}.amazonaws.com", "s3.amazonaws.com"}:
        path = unquote(parsed.path.lstrip("/"))
        bucket_prefix = f"{settings.s3_bucket_name}/"
        if path.startswith(bucket_prefix):
            return path[len(bucket_prefix) :]

    return None


def _extract_object_key_from_view_url(raw_url: str) -> str | None:
    parsed = urlparse(raw_url)
    if not parsed.path.rstrip("/").endswith("/upload/view"):
        return None

    query = parse_qs(parsed.query)
    object_key_values = query.get("object_key")
    if not object_key_values:
        return None

    return unquote(object_key_values[0]).strip().lstrip("/")


def extract_managed_user_upload_key(raw_url: str | None) -> str | None:
    if not raw_url:
        return None

    settings = get_settings()
    normalized = raw_url.strip()
    if not normalized:
        return None

    if normalized.startswith(settings.s3_user_uploads_prefix):
        return normalized

    object_key = _extract_object_key_from_view_url(normalized)
    if object_key is None:
        object_key = _extract_object_key_from_s3_url(normalized)

    if object_key is None:
        marker = f"/{settings.s3_user_uploads_prefix}"
        marker_index = normalized.find(marker)
        if marker_index >= 0:
            object_key = normalized[marker_index + 1 :]

    if not object_key:
        return None

    final_key = object_key.strip().lstrip("/")
    if not final_key.startswith(settings.s3_user_uploads_prefix):
        return None

    return final_key


def build_avatar_display_url(raw_avatar_url: str | None) -> tuple[str | None, datetime | None]:
    if not raw_avatar_url:
        return None, None

    normalized_avatar = raw_avatar_url.strip()
    if not normalized_avatar:
        return None, None

    settings = get_settings()
    object_key = extract_managed_user_upload_key(normalized_avatar)
    if not object_key:
        return normalized_avatar, None

    try:
        signed_url: str = _s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.s3_bucket_name,
                "Key": object_key,
            },
            ExpiresIn=settings.s3_presign_expiry_seconds,
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.s3_presign_expiry_seconds)
        return signed_url, expires_at
    except Exception:
        return normalized_avatar, None