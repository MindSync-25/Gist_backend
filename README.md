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
- `POST /api/v1/auth/sign-up` create user + issue access/refresh tokens
- `POST /api/v1/auth/sign-in` login + issue access/refresh tokens
- `POST /api/v1/auth/refresh` rotate refresh token + issue fresh access token
- `POST /api/v1/auth/logout` authenticated logout response (client clears local session)
- `GET /api/v1/auth/me` current authenticated user
- `GET /api/v1/topics` active topics list
- `GET /api/v1/characters` active characters list
- `GET /api/v1/posts?limit=20&offset=0` published posts feed
- `GET /api/v1/posts/{post_id}` post detail
- `GET /api/v1/posts/{post_id}/comments` post comments (supports parent filter)
- `POST /api/v1/posts/{post_id}/comments` create comment
- `POST /api/v1/posts/{post_id}/reactions` upsert user reaction

## Notes
- This is a production-oriented starter skeleton.
- Next modules to add: shares/bookmarks, voice APIs, series APIs, message APIs, rate limiting, caching.