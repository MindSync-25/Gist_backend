# Gist Backend

FastAPI backend scaffold aligned with Gist frontend + Gist Image Generator database.

## Stack
- FastAPI + Uvicorn
- PostgreSQL (SQLAlchemy 2)
- Pydantic Settings

## Quick start
1. Create env file from template:
	- Copy `.env.template` to `.env`
2. Fill DB credentials in `.env`
3. Create virtual environment and install deps:
	- `pip install -r requirements.txt`
4. Run API:
	- `uvicorn app.main:app --reload --port 8000`

## Endpoints
- `GET /` service metadata
- `GET /api/v1/health` liveness check
- `GET /api/v1/health/db` database connectivity check
- `GET /api/v1/comics?limit=20&offset=0` paginated comics feed from `public.comics`

## Notes
- This is a production-oriented starter skeleton.
- Next modules to add: auth, users, communities, posts/reactions/comments, rate limiting, caching.