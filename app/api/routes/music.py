from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

import boto3
from botocore.config import Config

from app.core.config import get_settings
from app.core.database import get_db

router = APIRouter(prefix="/music", tags=["music"])

PRESIGN_EXPIRY = 3600  # 1 hour


def _get_music_client():
    """Boto3 client using the dedicated gist-music R2 credentials."""
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.r2_endpoint.rstrip("/"),
        aws_access_key_id=s.r2_music_access_key_id,
        aws_secret_access_key=s.r2_music_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _public_url(raw_url: str) -> str:
    """Return a public/presigned URL for a private R2 music asset."""
    settings = get_settings()
    public_base = settings.r2_music_public_base.strip().rstrip("/")

    if public_base:
        parsed = urlparse(raw_url)
        parts = parsed.path.lstrip("/").split("/", 1)
        if len(parts) == 2:
            return f"{public_base}/{parts[1]}"
        return raw_url

    try:
        parsed = urlparse(raw_url)
        parts = parsed.path.lstrip("/").split("/", 1)
        if len(parts) != 2:
            return raw_url
        bucket, key = parts
        return _get_music_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=PRESIGN_EXPIRY,
        )
    except Exception:
        return raw_url


@router.get("")
def list_music_tracks(
    mood: Optional[str] = Query(None, description="Filter by mood"),
    limit: int = Query(20, ge=1, le=100, description="Max tracks to return"),
    db: Session = Depends(get_db),
):
    """Return active music tracks with presigned R2 URLs."""
    params: dict = {"limit": limit}
    where_clauses = ["is_active = TRUE"]

    if mood:
        where_clauses.append("mood = :mood")
        params["mood"] = mood

    where_sql = " AND ".join(where_clauses)
    rows = db.execute(
        text(
            f"SELECT id, title, mood, language_hint, style_tags, r2_public_url, duration_seconds"
            f" FROM music_tracks WHERE {where_sql} ORDER BY created_at DESC LIMIT :limit"
        ),
        params,
    ).fetchall()

    return [
        {
            "id": row.id,
            "title": row.title,
            "mood": row.mood,
            "language_hint": row.language_hint,
            "style_tags": row.style_tags or [],
            "url": _public_url(row.r2_public_url),
            "duration_seconds": row.duration_seconds,
        }
        for row in rows
    ]
