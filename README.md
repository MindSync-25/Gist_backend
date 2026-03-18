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

## Local First, AWS Later
- Recommended during development: run PostgreSQL locally to avoid cloud costs.
- This repo includes a bootstrap script that creates a local Postgres container and applies schema:
	- `powershell -ExecutionPolicy Bypass -File .\scripts\setup_local_postgres.ps1`

After the script runs, use these local DB values in `.env`:
- `DB_HOST=localhost`
- `DB_PORT=5432`
- `DB_NAME=gist`
- `DB_USER=gist`
- `DB_PASSWORD=gistpass`

To switch to AWS later, keep the same schema and only change DB env values:
- `DB_HOST=<your-rds-endpoint>`
- `DB_PORT=5432`
- `DB_NAME=<your-db-name>`
- `DB_USER=<your-db-user>`
- `DB_PASSWORD=<your-db-password>`

Then apply schema to AWS Postgres (from local machine with `psql`):
- `psql "host=<your-rds-endpoint> port=5432 dbname=<your-db-name> user=<your-db-user> password=<your-db-password>" -f .\app\db\001_initial_platform_schema.sql`

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