-- Monetization: 100k views / 60 days unlock, video-only 40% ad revenue share,
-- and $50 withdrawal gate.

CREATE TABLE IF NOT EXISTS monetization_profiles (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    monetization_unlocked_at TIMESTAMPTZ,
    wallet_balance_cents INT NOT NULL DEFAULT 0,
    total_earned_cents INT NOT NULL DEFAULT 0,
    total_withdrawn_cents INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
);

CREATE INDEX IF NOT EXISTS idx_content_view_events_owner_viewed
ON content_view_events (owner_user_id, viewed_at DESC);

CREATE INDEX IF NOT EXISTS idx_content_view_events_content_viewed
ON content_view_events (content_type, content_id, viewed_at DESC);

CREATE INDEX IF NOT EXISTS idx_content_view_events_viewer_viewed
ON content_view_events (viewer_user_id, viewed_at DESC)
WHERE viewer_user_id IS NOT NULL;

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
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ad_revenue_events_external_event_id
ON ad_revenue_events (external_event_id)
WHERE external_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ad_revenue_events_owner_occurred
ON ad_revenue_events (owner_user_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_ad_revenue_events_content_occurred
ON ad_revenue_events (content_type, content_id, occurred_at DESC);

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
);

CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_user_requested
ON withdrawal_requests (user_id, requested_at DESC);
