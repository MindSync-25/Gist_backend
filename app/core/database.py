from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

# When using transaction poolers (such as Supabase pgBouncer on 6543),
# SQLAlchemy's own pool should be disabled because pooling is external.
if settings.db_use_pgbouncer_effective:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_runtime_schema() -> None:
    """Apply safe runtime schema adjustments for any environment."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS location VARCHAR(120)"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS language VARCHAR(10) NOT NULL DEFAULT 'en'"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS date_of_birth DATE"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS google_sub VARCHAR(255)"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS apple_sub VARCHAR(255)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_sub ON users (google_sub) WHERE google_sub IS NOT NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_apple_sub ON users (apple_sub) WHERE apple_sub IS NOT NULL"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS auth_signup_otps (
                    id BIGSERIAL PRIMARY KEY,
                    email VARCHAR(255) NOT NULL,
                    username VARCHAR(50) NOT NULL,
                    display_name VARCHAR(80) NOT NULL,
                    date_of_birth DATE NOT NULL,
                    password_hash TEXT NOT NULL,
                    otp_hash TEXT NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    consumed_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_auth_signup_otps_email ON auth_signup_otps (email, created_at DESC)"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS auth_password_reset_otps (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    email VARCHAR(255) NOT NULL,
                    otp_hash TEXT NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    consumed_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_auth_password_reset_otps_email ON auth_password_reset_otps (email, created_at DESC)"))
        # Older local schemas from 001 set voice_takes.stance as NOT NULL.
        # Voice comments can be neutral (no stance), so we normalize this at startup.
        conn.execute(text("ALTER TABLE IF EXISTS voice_takes ALTER COLUMN stance DROP NOT NULL"))
