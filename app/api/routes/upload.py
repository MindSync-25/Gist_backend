import mimetypes
import uuid
from datetime import date
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.r2 import build_r2_object_url, get_r2_client, presign_r2_get, r2_bucket_for_content_type
from app.models.user import User

router = APIRouter(prefix="/upload", tags=["upload"])


ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/quicktime",
    "video/webm",
    # Audio — used for user-uploaded background music
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/aac",
    "audio/wav",
    "audio/ogg",
    "audio/flac",
}

MAX_FILE_SIZE_BYTES = 80 * 1024 * 1024  # 80 MB


@lru_cache
def _s3_client():
    import boto3

    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.Session(**kwargs).client("s3", region_name=settings.aws_region)


class PresignResponse(BaseModel):
    upload_url: str       # PUT to this URL directly from the client
    object_key: str       # pass this back when creating the post
    public_url: str       # the final image_url to store on the post


class ProxyUploadResponse(BaseModel):
    object_key: str
    public_url: str


def _build_object_key(content_type: str, user_id: int) -> str:
    settings = get_settings()
    ext = mimetypes.guess_extension(content_type) or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"
    today = date.today().isoformat()
    unique_id = uuid.uuid4().hex[:12]
    return f"{settings.r2_user_uploads_prefix}{today}/user-{user_id}/{unique_id}{ext}"


def _validate_user_upload_key(object_key: str) -> str:
    settings = get_settings()
    normalized_key = object_key.strip().lstrip("/")
    if not normalized_key:
        raise HTTPException(status_code=400, detail="object_key is required")
    if not normalized_key.startswith(settings.r2_user_uploads_prefix):
        raise HTTPException(status_code=400, detail="object_key must point to user uploads")
    return normalized_key


def _ensure_owned_user_upload_key(object_key: str, user_id: int) -> str:
    normalized_key = _validate_user_upload_key(object_key)
    owner_marker = f"/user-{user_id}/"
    if owner_marker not in f"/{normalized_key}":
        raise HTTPException(status_code=403, detail="Upload does not belong to current user")
    return normalized_key


@router.get("/presign", response_model=PresignResponse)
def presign_upload(
    filename: str = Query(..., min_length=1, max_length=200),
    content_type: str = Query(..., min_length=1, max_length=100),
    user_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
) -> PresignResponse:
    """
    Issue a short-lived presigned PUT URL so the client can upload directly to R2.

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
    object_key = _build_object_key(content_type, int(current_user.id))
    bucket = r2_bucket_for_content_type(content_type)

    try:
        upload_url: str = get_r2_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=settings.r2_presign_expiry_seconds,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"R2 presign failed: {exc}") from exc

    public_url = build_r2_object_url(bucket, object_key)

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
    user_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
) -> ProxyUploadResponse:
    """Fallback upload path when browser-to-R2 PUT fails."""
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

    object_key = _build_object_key(content_type, int(current_user.id))
    bucket = r2_bucket_for_content_type(content_type)

    try:
        get_r2_client().put_object(
            Bucket=bucket,
            Key=object_key,
            Body=body,
            ContentType=content_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"R2 proxy upload failed: {exc}") from exc

    return ProxyUploadResponse(
        object_key=object_key,
        public_url=build_r2_object_url(bucket, object_key),
    )


@router.get("/view")
def view_upload(object_key: str = Query(..., min_length=1, max_length=1024)) -> RedirectResponse:
    """Return a redirect to a short-lived signed GET URL for a user-uploaded object."""
    settings = get_settings()
    normalized_key = _validate_user_upload_key(object_key)
    # Determine bucket from key prefix (images bucket for user-uploads)
    bucket = settings.r2_images_bucket

    try:
        signed_get_url: str = get_r2_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": normalized_key},
            ExpiresIn=settings.r2_presign_expiry_seconds,
        )
    except Exception:
        # Legacy fallback: older user uploads may still be in S3.
        try:
            signed_get_url = _s3_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.s3_bucket_name, "Key": normalized_key},
                ExpiresIn=settings.s3_presign_expiry_seconds,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Signed view failed: {exc}") from exc

    return RedirectResponse(url=signed_get_url, status_code=307)


# ── Audio trim ────────────────────────────────────────────────────────────────

class TrimAudioRequest(BaseModel):
    audio_url: str
    start_secs: float = Field(default=0, ge=0)
    duration_secs: float = Field(gt=0, le=180)


class TrimAudioResponse(BaseModel):
    public_url: str


@router.post("/trim-audio", response_model=TrimAudioResponse)
def trim_audio(
    body: TrimAudioRequest,
    current_user: User = Depends(get_current_user),
) -> TrimAudioResponse:
    """
    Download an audio file from R2, trim it to the requested clip window,
    re-upload the trimmed MP3, and delete the original to save storage.
    Returns the public URL of the trimmed file.
    """
    import io

    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Audio processing unavailable: pydub not installed",
        ) from exc

    from app.core.r2 import extract_r2_bucket_and_key

    r2_ref = extract_r2_bucket_and_key(body.audio_url)
    if not r2_ref:
        raise HTTPException(status_code=422, detail="audio_url must be an R2 object URL")

    bucket, key = r2_ref

    # Reject keys that don't belong to user-uploads (security guard)
    settings = get_settings()
    _ensure_owned_user_upload_key(key, int(current_user.id))

    client = get_r2_client()

    # Download original audio from R2
    try:
        obj = client.get_object(Bucket=bucket, Key=key)
        audio_bytes = obj["Body"].read()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch audio from R2: {exc}") from exc

    # Determine format from key extension
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else "mp3"
    fmt_map = {
        "mp3": "mp3", "m4a": "mp4", "mp4": "mp4",
        "aac": "aac", "wav": "wav", "ogg": "ogg", "flac": "flac",
    }
    fmt = fmt_map.get(ext, "mp3")

    # Trim
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=fmt)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not decode audio: {exc}") from exc

    start_ms = int(body.start_secs * 1000)
    end_ms = int((body.start_secs + body.duration_secs) * 1000)
    clipped = audio[start_ms:min(end_ms, len(audio))]

    # Export as MP3 (universal playback)
    out_buf = io.BytesIO()
    clipped.export(out_buf, format="mp3", bitrate="128k")
    out_buf.seek(0)

    # Upload trimmed clip under a new key (same prefix, _clip suffix)
    base_key = key.rsplit(".", 1)[0] if "." in key else key
    new_key = f"{base_key}_clip.mp3"
    try:
        client.put_object(
            Bucket=bucket,
            Key=new_key,
            Body=out_buf.getvalue(),
            ContentType="audio/mpeg",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to upload trimmed audio: {exc}") from exc

    # Delete original to reclaim storage (best-effort)
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass

    return TrimAudioResponse(public_url=build_r2_object_url(bucket, new_key))


# ── Audio delete (cleanup on post cancel) ─────────────────────────────────────

class DeleteAudioRequest(BaseModel):
    audio_url: str


@router.delete("/audio")
def delete_audio(
    body: DeleteAudioRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Delete a user-uploaded audio file from R2.
    Called by the client when a post is discarded so orphaned uploads are removed.
    Only files under the user-uploads prefix may be deleted.
    """
    from app.core.r2 import extract_r2_bucket_and_key

    r2_ref = extract_r2_bucket_and_key(body.audio_url)
    if not r2_ref:
        raise HTTPException(status_code=422, detail="audio_url must be an R2 object URL")

    bucket, key = r2_ref

    _ensure_owned_user_upload_key(key, int(current_user.id))

    try:
        get_r2_client().delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass  # best-effort — don't fail the client on cleanup errors

    return {"deleted": True}
