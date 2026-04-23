"""
r2.py — Shared Cloudflare R2 client and URL helpers.

Used by upload.py, posts.py, avatar_signing.py for user content.
Comics (ImageGenerator) continue to use AWS S3 directly.
"""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from botocore.config import Config

from app.core.config import get_settings


@lru_cache
def get_r2_client():
    import boto3

    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint.rstrip("/"),
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def r2_bucket_for_content_type(content_type: str) -> str:
    """Return the correct R2 bucket based on whether content is video or image."""
    settings = get_settings()
    if content_type.startswith("video/"):
        return settings.r2_videos_bucket
    return settings.r2_images_bucket


def build_r2_object_url(bucket: str, key: str) -> str:
    """Build the full static R2 URL for a stored object (used as the persisted URL in DB)."""
    settings = get_settings()
    return f"{settings.r2_endpoint.rstrip('/')}/{bucket}/{key}"


def is_r2_url(url: str) -> bool:
    """Return True if the URL points to our Cloudflare R2 account."""
    return "r2.cloudflarestorage.com" in url.lower()


def extract_r2_bucket_and_key(url: str) -> tuple[str, str] | None:
    """
    Parse an R2 URL into (bucket, key).
    URL format: https://ACCOUNT.r2.cloudflarestorage.com/BUCKET/KEY
    Returns None if not a recognisable R2 URL.
    """
    if not is_r2_url(url):
        return None
    parsed = urlparse(url)
    # path = /BUCKET/KEY...
    path = parsed.path.lstrip("/")
    if "/" not in path:
        return None
    bucket, key = path.split("/", 1)
    if not bucket or not key:
        return None
    return bucket, key


def presign_r2_get(url: str) -> str:
    """
    Given a stored R2 object URL, return a fresh presigned GET URL.
    Falls back to the original URL if parsing or signing fails.
    """
    result = extract_r2_bucket_and_key(url)
    if result is None:
        return url
    bucket, key = result
    settings = get_settings()
    try:
        return get_r2_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=settings.r2_content_presign_expiry_seconds,
        )
    except Exception:
        return url
