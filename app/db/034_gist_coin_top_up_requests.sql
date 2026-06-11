-- Top-up request workflow for GIST Coins.
-- Users submit top-up requests, admin approves and credits coins.

BEGIN;

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
    CONSTRAINT ck_gist_coin_top_up_requests_status
        CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_gist_coin_top_up_requests_user_status
    ON gist_coin_top_up_requests (user_id, status, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_gist_coin_top_up_requests_provider_reference
    ON gist_coin_top_up_requests (provider_reference_id)
    WHERE provider_reference_id IS NOT NULL;

ALTER TABLE gist_coin_top_up_requests ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS gist_coin_top_up_requests_select_own ON gist_coin_top_up_requests;
CREATE POLICY gist_coin_top_up_requests_select_own
ON gist_coin_top_up_requests
FOR SELECT
USING (
    user_id = NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
    OR user_id = NULLIF(auth.jwt() ->> 'gist_user_id', '')::BIGINT
);

COMMIT;
