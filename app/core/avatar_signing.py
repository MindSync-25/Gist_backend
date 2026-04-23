from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import parse_qs, unquote, urlparse

from app.core.config import get_settings
from app.core.r2 import get_r2_client, is_r2_url


@lru_cache
def _s3_client():
    import boto3

    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.Session(**kwargs).client("s3", region_name=settings.aws_region)


def _extract_s3_bucket_and_key(raw_url: str) -> tuple[str, str] | None:
    parsed = urlparse(raw_url)
    host = (parsed.netloc or "").lower()
    path = parsed.path.lstrip("/")
    if not path:
        return None

    if ".s3." in host and host.endswith("amazonaws.com"):
        bucket = host.split(".s3.", 1)[0]
        if bucket and path:
            return bucket, path

    if (host.startswith("s3.") or host == "s3.amazonaws.com") and "/" in path:
        bucket, key = path.split("/", 1)
        if bucket and key:
            return bucket, key

    return None


def _extract_object_key_from_r2_url(raw_url: str) -> str | None:
    """Extract object key from a full R2 URL: https://ACCOUNT.r2.../BUCKET/KEY"""
    if not is_r2_url(raw_url):
        return None
    parsed = urlparse(raw_url)
    path = parsed.path.lstrip("/")
    if "/" not in path:
        return None
    _, key = path.split("/", 1)
    return key or None


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

    if normalized.startswith(settings.r2_user_uploads_prefix):
        return normalized

    object_key = _extract_object_key_from_view_url(normalized)
    if object_key is None:
        object_key = _extract_object_key_from_r2_url(normalized)

    if object_key is None:
        marker = f"/{settings.r2_user_uploads_prefix}"
        marker_index = normalized.find(marker)
        if marker_index >= 0:
            object_key = normalized[marker_index + 1:]

    if not object_key:
        return None

    final_key = object_key.strip().lstrip("/")
    if not final_key.startswith(settings.r2_user_uploads_prefix):
        return None

    return final_key


def build_avatar_display_url(raw_avatar_url: str | None) -> tuple[str | None, datetime | None]:
    if not raw_avatar_url:
        return None, None

    normalized_avatar = raw_avatar_url.strip()
    if not normalized_avatar:
        return None, None

    # Legacy S3-stored avatars: serve with fresh S3 presigned URL.
    s3_ref = _extract_s3_bucket_and_key(normalized_avatar)
    if s3_ref is not None:
        bucket, key = s3_ref
        settings = get_settings()
        try:
            signed_url: str = _s3_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=settings.s3_content_presign_expiry_seconds,
            )
            expires_at = datetime.now(UTC) + timedelta(seconds=settings.s3_content_presign_expiry_seconds)
            return signed_url, expires_at
        except Exception:
            return normalized_avatar, None

    settings = get_settings()
    object_key = extract_managed_user_upload_key(normalized_avatar)
    if not object_key:
        return normalized_avatar, None

    try:
        signed_url: str = get_r2_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.r2_images_bucket,
                "Key": object_key,
            },
            ExpiresIn=settings.r2_content_presign_expiry_seconds,
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.r2_content_presign_expiry_seconds)
        return signed_url, expires_at
    except Exception:
        return normalized_avatar, None