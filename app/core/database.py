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
        # Avoid blocking app startup on long-held DDL locks in production.
        conn.execute(text("SET LOCAL lock_timeout = '2s'"))
        conn.execute(text("SET LOCAL statement_timeout = '10s'"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS location VARCHAR(120)"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS language VARCHAR(10) NOT NULL DEFAULT 'en'"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS account_type VARCHAR(20) NOT NULL DEFAULT 'personal'"))
        conn.execute(text("UPDATE users SET account_type = 'personal' WHERE account_type IS NULL OR account_type NOT IN ('personal', 'professional')"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS date_of_birth DATE"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS expo_push_token TEXT"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS fcm_push_token TEXT"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS google_sub VARCHAR(255)"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS apple_sub VARCHAR(255)"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS referred_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS referred_by_invite_link_id BIGINT"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS invite_activated_at TIMESTAMPTZ"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_expo_push_token ON users (expo_push_token) WHERE expo_push_token IS NOT NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_fcm_push_token ON users (fcm_push_token) WHERE fcm_push_token IS NOT NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_sub ON users (google_sub) WHERE google_sub IS NOT NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_apple_sub ON users (apple_sub) WHERE apple_sub IS NOT NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_referred_by_user ON users (referred_by_user_id) WHERE referred_by_user_id IS NOT NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_referred_by_invite ON users (referred_by_invite_link_id) WHERE referred_by_invite_link_id IS NOT NULL"))

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
        conn.execute(text("ALTER TABLE IF EXISTS auth_signup_otps ADD COLUMN IF NOT EXISTS invite_token VARCHAR(120)"))

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
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS invite_links (
                    id BIGSERIAL PRIMARY KEY,
                    inviter_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token VARCHAR(120) NOT NULL UNIQUE,
                    invite_type VARCHAR(30) NOT NULL DEFAULT 'generic',
                    target_entity_type VARCHAR(30),
                    target_entity_id BIGINT,
                    channel VARCHAR(30) NOT NULL DEFAULT 'native_share',
                    opens_count INT NOT NULL DEFAULT 0,
                    last_opened_at TIMESTAMPTZ,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CHECK (invite_type IN ('generic', 'profile', 'post', 'voice')),
                    CHECK (channel IN ('native_share', 'copy_link', 'external_social', 'dm'))
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_invite_links_inviter ON invite_links (inviter_user_id, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_invite_links_target ON invite_links (target_entity_type, target_entity_id)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS invite_events (
                    id BIGSERIAL PRIMARY KEY,
                    invite_link_id BIGINT NOT NULL REFERENCES invite_links(id) ON DELETE CASCADE,
                    event_type VARCHAR(20) NOT NULL,
                    actor_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                    subject_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CHECK (event_type IN ('open', 'signup', 'activate'))
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_invite_events_link ON invite_events (invite_link_id, event_type, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_invite_events_subject ON invite_events (subject_user_id, event_type, created_at DESC) WHERE subject_user_id IS NOT NULL"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    id BIGSERIAL PRIMARY KEY,
                    creator_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    statement VARCHAR(280) NOT NULL,
                    context TEXT NOT NULL DEFAULT '',
                    topic VARCHAR(80),
                    estimates_count INT NOT NULL DEFAULT 0,
                    estimates_sum INT NOT NULL DEFAULT 0,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_predictions_active_created ON predictions (is_active, created_at DESC)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS prediction_estimates (
                    id BIGSERIAL PRIMARY KEY,
                    prediction_id BIGINT NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    estimate_percent INT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_prediction_estimates_prediction_user UNIQUE (prediction_id, user_id),
                    CONSTRAINT ck_prediction_estimates_percent CHECK (estimate_percent >= 1 AND estimate_percent <= 100)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prediction_estimates_user ON prediction_estimates (user_id, updated_at DESC)"))
        # Older local schemas from 001 set voice_takes.stance as NOT NULL.
        # Voice comments can be neutral (no stance), so we normalize this at startup.
        conn.execute(text("ALTER TABLE IF EXISTS voice_takes ALTER COLUMN stance DROP NOT NULL"))
        conn.execute(text("ALTER TABLE IF EXISTS voice_takes ADD COLUMN IF NOT EXISTS audio_url TEXT"))
        conn.execute(text("ALTER TABLE IF EXISTS voice_takes ADD COLUMN IF NOT EXISTS audio_duration_sec INTEGER"))

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
                CREATE TABLE IF NOT EXISTS voice_live_sessions (
                    id BIGSERIAL PRIMARY KEY,
                    issue_id BIGINT NOT NULL REFERENCES voice_issues(id) ON DELETE CASCADE,
                    host_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                    room_slug VARCHAR(160) NOT NULL UNIQUE,
                    provider VARCHAR(40) NOT NULL DEFAULT 'livekit',
                    join_url TEXT NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    max_participants INTEGER NOT NULL DEFAULT 8,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    ended_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_voice_live_sessions_status CHECK (status IN ('active', 'ended')),
                    CONSTRAINT ck_voice_live_sessions_max_participants CHECK (max_participants BETWEEN 2 AND 8)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_voice_live_sessions_issue_status ON voice_live_sessions (issue_id, status, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_voice_live_sessions_host ON voice_live_sessions (host_user_id, created_at DESC) WHERE host_user_id IS NOT NULL"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS voice_live_participants (
                    id BIGSERIAL PRIMARY KEY,
                    session_id BIGINT NOT NULL REFERENCES voice_live_sessions(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role VARCHAR(20) NOT NULL DEFAULT 'member',
                    status VARCHAR(20) NOT NULL DEFAULT 'invited',
                    invited_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                    joined_at TIMESTAMPTZ,
                    left_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_voice_live_participants_session_user UNIQUE (session_id, user_id),
                    CONSTRAINT ck_voice_live_participants_role CHECK (role IN ('host', 'member')),
                    CONSTRAINT ck_voice_live_participants_status CHECK (status IN ('invited', 'joined', 'left'))
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_voice_live_participants_session_status ON voice_live_participants (session_id, status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_voice_live_participants_user_created ON voice_live_participants (user_id, created_at DESC)"))

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

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS monetization_profiles (
                    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    monetization_unlocked_at TIMESTAMPTZ,
                    wallet_balance_cents INT NOT NULL DEFAULT 0,
                    total_earned_cents INT NOT NULL DEFAULT 0,
                    total_withdrawn_cents INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS content_view_events (
                    id BIGSERIAL PRIMARY KEY,
                    content_type VARCHAR(20) NOT NULL,
                    content_id BIGINT NOT NULL,
                    owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    viewer_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                    viewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    source VARCHAR(40),
                    session_key VARCHAR(120),
                    CONSTRAINT ck_content_view_events_type CHECK (content_type IN ('post', 'short', 'comic'))
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_content_view_events_owner_viewed ON content_view_events (owner_user_id, viewed_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_content_view_events_content_viewed ON content_view_events (content_type, content_id, viewed_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_content_view_events_viewer_viewed ON content_view_events (viewer_user_id, viewed_at DESC) WHERE viewer_user_id IS NOT NULL"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ad_revenue_events (
                    id BIGSERIAL PRIMARY KEY,
                    content_type VARCHAR(20) NOT NULL,
                    content_id BIGINT NOT NULL,
                    owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    gross_revenue_cents INT NOT NULL,
                    creator_share_cents INT NOT NULL DEFAULT 0,
                    gist_share_cents INT NOT NULL DEFAULT 0,
                    eligible_at_event BOOLEAN NOT NULL DEFAULT FALSE,
                    is_video_content BOOLEAN NOT NULL DEFAULT FALSE,
                    revenue_source VARCHAR(40) NOT NULL DEFAULT 'ad_network',
                    external_event_id VARCHAR(120),
                    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_ad_revenue_events_type CHECK (content_type IN ('post', 'short', 'comic'))
                )
                """
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_ad_revenue_events_external_event_id ON ad_revenue_events (external_event_id) WHERE external_event_id IS NOT NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ad_revenue_events_owner_occurred ON ad_revenue_events (owner_user_id, occurred_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ad_revenue_events_content_occurred ON ad_revenue_events (content_type, content_id, occurred_at DESC)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS withdrawal_requests (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    amount_cents INT NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    payout_method VARCHAR(40),
                    payout_note TEXT,
                    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_withdrawal_requests_status CHECK (status IN ('pending', 'approved', 'paid', 'rejected', 'cancelled'))
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_user_requested ON withdrawal_requests (user_id, requested_at DESC)"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS gist_coin_wallets (
                    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    balance_coins BIGINT NOT NULL DEFAULT 0,
                    total_received_coins BIGINT NOT NULL DEFAULT 0,
                    total_spent_coins BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_gist_coin_wallets_balance_nonnegative CHECK (balance_coins >= 0),
                    CONSTRAINT ck_gist_coin_wallets_received_nonnegative CHECK (total_received_coins >= 0),
                    CONSTRAINT ck_gist_coin_wallets_spent_nonnegative CHECK (total_spent_coins >= 0)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS gist_tip_transactions (
                    id BIGSERIAL PRIMARY KEY,
                    sender_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    recipient_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    content_type VARCHAR(20) NOT NULL,
                    content_id BIGINT NOT NULL,
                    amount_coins BIGINT NOT NULL,
                    creator_share_coins BIGINT NOT NULL,
                    platform_fee_coins BIGINT NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'succeeded',
                    message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_gist_tip_transactions_content_type CHECK (content_type IN ('post', 'short')),
                    CONSTRAINT ck_gist_tip_transactions_amount_positive CHECK (amount_coins > 0),
                    CONSTRAINT ck_gist_tip_transactions_creator_share_nonnegative CHECK (creator_share_coins >= 0),
                    CONSTRAINT ck_gist_tip_transactions_platform_fee_nonnegative CHECK (platform_fee_coins >= 0),
                    CONSTRAINT ck_gist_tip_transactions_status CHECK (status IN ('succeeded', 'failed', 'refunded')),
                    CONSTRAINT ck_gist_tip_transactions_split CHECK (amount_coins = creator_share_coins + platform_fee_coins),
                    CONSTRAINT ck_gist_tip_transactions_no_self_tip CHECK (sender_user_id <> recipient_user_id)
                )
                """
            )
        )
        conn.execute(text("ALTER TABLE gist_tip_transactions DROP CONSTRAINT IF EXISTS ck_gist_tip_transactions_amount_exact_split"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gist_tip_transactions_sender_created ON gist_tip_transactions (sender_user_id, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gist_tip_transactions_recipient_created ON gist_tip_transactions (recipient_user_id, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gist_tip_transactions_content_created ON gist_tip_transactions (content_type, content_id, created_at DESC)"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS gist_coin_transactions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    direction VARCHAR(10) NOT NULL,
                    transaction_type VARCHAR(30) NOT NULL,
                    amount_coins BIGINT NOT NULL,
                    balance_after_coins BIGINT NOT NULL,
                    counterparty_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                    content_type VARCHAR(20),
                    content_id BIGINT,
                    reference_type VARCHAR(30),
                    reference_id BIGINT,
                    note TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_gist_coin_transactions_direction CHECK (direction IN ('credit', 'debit')),
                    CONSTRAINT ck_gist_coin_transactions_type CHECK (transaction_type IN ('tip_sent', 'tip_received', 'platform_fee', 'admin_grant', 'purchase')),
                    CONSTRAINT ck_gist_coin_transactions_amount_positive CHECK (amount_coins > 0),
                    CONSTRAINT ck_gist_coin_transactions_balance_nonnegative CHECK (balance_after_coins >= 0)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gist_coin_transactions_user_created ON gist_coin_transactions (user_id, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gist_coin_transactions_reference ON gist_coin_transactions (reference_type, reference_id) WHERE reference_type IS NOT NULL AND reference_id IS NOT NULL"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS gist_coin_top_up_requests (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    amount_coins BIGINT NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    source VARCHAR(32),
                    provider_reference_id VARCHAR(160),
                    note TEXT,
                    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_gist_coin_top_up_requests_status CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled'))
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_gist_coin_top_up_requests_user_status ON gist_coin_top_up_requests (user_id, status, requested_at DESC)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_gist_coin_top_up_requests_provider_reference ON gist_coin_top_up_requests (provider_reference_id) WHERE provider_reference_id IS NOT NULL"
            )
        )
        conn.execute(text("ALTER TABLE gist_coin_wallets ENABLE ROW LEVEL SECURITY"))
        conn.execute(
            text(
                "DROP POLICY IF EXISTS gist_coin_wallets_select_own ON gist_coin_wallets"
            )
        )
        conn.execute(
            text(
                """
                CREATE POLICY gist_coin_wallets_select_own
                ON gist_coin_wallets
                FOR SELECT
                USING (
                    user_id = NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
                    OR user_id = NULLIF(auth.jwt() ->> 'gist_user_id', '')::BIGINT
                )
                """
            )
        )
        conn.execute(text("ALTER TABLE gist_coin_transactions ENABLE ROW LEVEL SECURITY"))
        conn.execute(
            text(
                "DROP POLICY IF EXISTS gist_coin_transactions_select_own ON gist_coin_transactions"
            )
        )
        conn.execute(
            text(
                """
                CREATE POLICY gist_coin_transactions_select_own
                ON gist_coin_transactions
                FOR SELECT
                USING (
                    user_id = NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
                    OR user_id = NULLIF(auth.jwt() ->> 'gist_user_id', '')::BIGINT
                )
                """
            )
        )
        conn.execute(text("ALTER TABLE gist_tip_transactions ENABLE ROW LEVEL SECURITY"))
        conn.execute(
            text(
                "DROP POLICY IF EXISTS gist_tip_transactions_select_participant ON gist_tip_transactions"
            )
        )
        conn.execute(
            text(
                """
                CREATE POLICY gist_tip_transactions_select_participant
                ON gist_tip_transactions
                FOR SELECT
                USING (
                    sender_user_id = NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
                    OR recipient_user_id = NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
                    OR sender_user_id = NULLIF(auth.jwt() ->> 'gist_user_id', '')::BIGINT
                    OR recipient_user_id = NULLIF(auth.jwt() ->> 'gist_user_id', '')::BIGINT
                )
                """
            )
        )
        conn.execute(text("ALTER TABLE gist_coin_top_up_requests ENABLE ROW LEVEL SECURITY"))
        conn.execute(
            text(
                "DROP POLICY IF EXISTS gist_coin_top_up_requests_select_own ON gist_coin_top_up_requests"
            )
        )
        conn.execute(
            text(
                """
                CREATE POLICY gist_coin_top_up_requests_select_own
                ON gist_coin_top_up_requests
                FOR SELECT
                USING (
                    user_id = NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
                    OR user_id = NULLIF(auth.jwt() ->> 'gist_user_id', '')::BIGINT
                )
                """
            )
        )

        # Per-user daily AI chat usage counter (cost control)
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ai_daily_usage (
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    chat_count INT NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, usage_date)
                )
                """
            )
        )
