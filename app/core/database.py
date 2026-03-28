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
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS expo_push_token TEXT"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS fcm_push_token TEXT"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS google_sub VARCHAR(255)"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS apple_sub VARCHAR(255)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_expo_push_token ON users (expo_push_token) WHERE expo_push_token IS NOT NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_fcm_push_token ON users (fcm_push_token) WHERE fcm_push_token IS NOT NULL"))
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

        # Backfill older voice schemas that missed the slug column.
        conn.execute(text("ALTER TABLE IF EXISTS voice_issues ADD COLUMN IF NOT EXISTS slug VARCHAR(300)"))
        conn.execute(
            text(
                """
                UPDATE voice_issues
                SET slug = (
                    COALESCE(NULLIF(lower(replace(trim(title), ' ', '-')), ''), 'issue')
                    || '-' || id::text
                )
                WHERE slug IS NULL OR slug = ''
                """
            )
        )
        conn.execute(text("ALTER TABLE IF EXISTS voice_issues ALTER COLUMN slug SET NOT NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_issues_slug ON voice_issues (slug)"))

        # Old schema used status='active'; new model expects status='open'/'closed'/'archived'.
        # Migrate existing rows and replace the check constraint.
        conn.execute(text("UPDATE voice_issues SET status = 'open' WHERE status = 'active'"))
        conn.execute(text("ALTER TABLE voice_issues DROP CONSTRAINT IF EXISTS voice_issues_status_check"))
        conn.execute(text("""
            DO $$
            DECLARE
                cname text;
            BEGIN
                SELECT conname INTO cname
                FROM pg_constraint
                WHERE conrelid = 'voice_issues'::regclass
                  AND contype = 'c'
                  AND conname NOT IN ('ck_voice_issues_created_by_type', 'voice_issues_status_check');
                IF cname IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE voice_issues DROP CONSTRAINT ' || quote_ident(cname);
                END IF;
            END $$
        """))
        conn.execute(text("""
            ALTER TABLE voice_issues
                ADD CONSTRAINT voice_issues_status_check
                CHECK (status IN ('open', 'closed', 'archived'))
        """))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sponsored_campaigns (
                    id BIGSERIAL PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    placement VARCHAR(30) NOT NULL DEFAULT 'home_feed',
                    sponsor_name VARCHAR(120) NOT NULL,
                    headline VARCHAR(180) NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    cta_label VARCHAR(40) NOT NULL DEFAULT 'Learn More',
                    target_url TEXT NOT NULL,
                    image_url TEXT NULL,
                    category VARCHAR(60) NULL,
                    priority INT NOT NULL DEFAULT 100,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    starts_at TIMESTAMPTZ NULL,
                    ends_at TIMESTAMPTZ NULL,
                    ad_network VARCHAR(30) NULL,
                    ad_unit_id VARCHAR(180) NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_sponsored_campaigns_placement CHECK (placement IN ('home_feed'))
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_sponsored_campaigns_feed_lookup ON sponsored_campaigns (placement, is_active, priority, id DESC)"
            )
        )
