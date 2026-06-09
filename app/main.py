import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.router import api_router
from app.api.routes.share import router as share_router
from app.core.config import get_settings
from app.core.database import SessionLocal, ensure_runtime_schema

settings = get_settings()
app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
# Public HTML share pages served at /share/post/{id} (no /api/v1 prefix)
app.include_router(share_router)

_scheduler = BackgroundScheduler()


def _run_hourly_interest_digest() -> None:
    db = SessionLocal()
    try:
        from app.core.notifications import send_hourly_interest_digest
        send_hourly_interest_digest(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hourly digest job error: %s", exc)
    finally:
        db.close()


@app.on_event("startup")
def startup_tasks() -> None:
    try:
        ensure_runtime_schema()
    except Exception as exc:
        logger.warning("Runtime schema check skipped: %s", exc)
    _scheduler.add_job(_run_hourly_interest_digest, "interval", hours=2, id="hourly_interest_digest")
    _scheduler.start()


@app.on_event("shutdown")
def shutdown_tasks() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.app_name, "env": settings.app_env}


@app.get("/app-ads.txt", response_class=PlainTextResponse)
def app_ads_txt() -> str:
    return "google.com, pub-9812277605594739, DIRECT, f08c47fec0942fa0\n"


@app.get("/.well-known/assetlinks.json")
def android_assetlinks() -> JSONResponse:
    # Comma-separated SHA256 fingerprints, ideally include Play App Signing cert.
    fingerprints_raw = os.getenv("ANDROID_APP_LINK_SHA256", "").strip()
    fingerprints = [fp.strip() for fp in fingerprints_raw.split(",") if fp.strip()]
    if not fingerprints:
        fingerprints = ["REPLACE_WITH_PLAY_APP_SIGNING_SHA256_FINGERPRINT"]

    payload = [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "com.gist.app",
                "sha256_cert_fingerprints": fingerprints,
            },
        }
    ]
    return JSONResponse(content=payload)
