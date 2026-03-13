from fastapi import APIRouter

from app.api.routes.comics import router as comics_router
from app.api.routes.health import router as health_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(comics_router)
