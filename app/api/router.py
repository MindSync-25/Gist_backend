from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.characters import router as characters_router
from app.api.routes.comics import router as comics_router
from app.api.routes.health import router as health_router
from app.api.routes.posts import router as posts_router
from app.api.routes.topics import router as topics_router
from app.api.routes.upload import router as upload_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(comics_router)
api_router.include_router(auth_router)
api_router.include_router(topics_router)
api_router.include_router(characters_router)
api_router.include_router(posts_router)
api_router.include_router(upload_router)
