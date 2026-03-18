import mimetypes
import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(prefix="/upload", tags=["upload"])


ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


class PresignResponse(BaseModel):
    upload_url: str       # PUT to this URL directly from the client
    object_key: str       # pass this back when creating the post
    public_url: str       # the final image_url to store on the post


class ProxyUploadResponse(BaseModel):
    object_key: str
    public_url: str


def _s3_client():
    import boto3
    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.Session(**kwargs).client("s3", region_name=settings.aws_region)


def _build_object_key(content_type: str, user_id: int) -> str:
    settings = get_settings()
    ext = mimetypes.guess_extension(content_type) or ".jpg"
    # Normalise .jpe -> .jpg
    if ext == ".jpe":
        ext = ".jpg"

    today = date.today().isoformat()
    unique_id = uuid.uuid4().hex[:12]
    return f"{settings.s3_user_uploads_prefix}{today}/user-{user_id}/{unique_id}{ext}"


def _build_public_url(object_key: str) -> str:
    settings = get_settings()
    return f"https://{settings.s3_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{object_key}"


def _validate_user_upload_key(object_key: str) -> str:
    settings = get_settings()
    normalized_key = object_key.strip().lstrip("/")
    if not normalized_key:
        raise HTTPException(status_code=400, detail="object_key is required")
    if not normalized_key.startswith(settings.s3_user_uploads_prefix):
        raise HTTPException(status_code=400, detail="object_key must point to user uploads")
    return normalized_key


@router.get("/presign", response_model=PresignResponse)
def presign_upload(
    filename: str = Query(..., min_length=1, max_length=200),
    content_type: str = Query(..., min_length=1, max_length=100),
    user_id: int = Query(..., ge=1),
) -> PresignResponse:
    """
    Issue a short-lived presigned PUT URL so the client can upload an image
    directly to S3 without routing bytes through the API server.

    Flow:
      1. Client calls GET /api/v1/upload/presign?filename=...&content_type=...&user_id=...
      2. Client PUTs the file bytes to upload_url (Content-Type header must match)
      3. Client calls POST /api/v1/posts with image_url = public_url
    """
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"content_type must be one of: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}",
        )

    settings = get_settings()
    object_key = _build_object_key(content_type, user_id)

    try:
        s3 = _s3_client()
        upload_url: str = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.s3_bucket_name,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=settings.s3_presign_expiry_seconds,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"S3 presign failed: {exc}") from exc

    public_url = _build_public_url(object_key)

    return PresignResponse(
        upload_url=upload_url,
        object_key=object_key,
        public_url=public_url,
    )


@router.post("/proxy", response_model=ProxyUploadResponse)
async def proxy_upload(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=200),
    content_type: str = Query(..., min_length=1, max_length=100),
    user_id: int = Query(..., ge=1),
) -> ProxyUploadResponse:
    """Fallback upload path when browser-to-S3 PUT fails (for example due to CORS)."""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"content_type must be one of: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}",
        )

    _ = filename
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty upload body")

    if len(body) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"Max upload size is {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB")

    settings = get_settings()
    object_key = _build_object_key(content_type, user_id)

    try:
        s3 = _s3_client()
        s3.put_object(
            Bucket=settings.s3_bucket_name,
            Key=object_key,
            Body=body,
            ContentType=content_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"S3 proxy upload failed: {exc}") from exc

    return ProxyUploadResponse(
        object_key=object_key,
        public_url=_build_public_url(object_key),
    )


@router.get("/view")
def view_upload(object_key: str = Query(..., min_length=1, max_length=1024)) -> RedirectResponse:
    """Return a redirect to a short-lived signed GET URL for private user-uploaded objects."""
    normalized_key = _validate_user_upload_key(object_key)
    settings = get_settings()

    try:
        s3 = _s3_client()
        signed_get_url: str = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.s3_bucket_name,
                "Key": normalized_key,
            },
            ExpiresIn=settings.s3_presign_expiry_seconds,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"S3 signed view failed: {exc}") from exc

    return RedirectResponse(url=signed_get_url, status_code=307)
