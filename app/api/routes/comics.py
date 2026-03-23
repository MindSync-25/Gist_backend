from functools import lru_cache

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.comic import Comic
from app.schemas.comic import ComicOut

router = APIRouter(prefix="/comics", tags=["comics"])


@lru_cache
def _s3_client():
    import boto3

    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.Session(**kwargs).client("s3", region_name=settings.aws_region)


def _fresh_url(s3_key: str | None) -> str | None:
    """Generate a fresh presigned GET URL from the stable s3_key."""
    if not s3_key:
        return None
    try:
        settings = get_settings()
        return _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_name, "Key": s3_key},
            ExpiresIn=settings.s3_content_presign_expiry_seconds,
        )
    except Exception:
        return None


@router.get("", response_model=list[ComicOut])
def list_comics(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ComicOut]:
    rows = db.execute(
        select(Comic)
        .where(func.coalesce(Comic.s3_key, "") != "")
        .order_by(desc(Comic.generated_at), desc(Comic.id))
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return [
        ComicOut(
            id=comic.id,
            article_url=comic.article_url,
            headline=comic.headline,
            category=comic.category,
            run_date=comic.run_date,
            tone=comic.tone,
            summary=comic.summary,
            banner_title=comic.banner_title,
            scene=comic.scene,
            hero_character=comic.hero_character,
            background=comic.background,
            dialogue=comic.dialogue,
            image_prompt=comic.image_prompt,
            s3_key=comic.s3_key,
            s3_url=_fresh_url(comic.s3_key) or comic.s3_url,
            generated_at=comic.generated_at,
        )
        for comic in rows
    ]
