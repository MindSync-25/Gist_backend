import logging

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
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
    _scheduler.add_job(_run_hourly_interest_digest, "interval", hours=1, id="hourly_interest_digest")
    _scheduler.start()


@app.on_event("shutdown")
def shutdown_tasks() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.app_name, "env": settings.app_env}
