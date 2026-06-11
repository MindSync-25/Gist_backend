-- GIST Coins: integer-only virtual coin economy for tipping.
-- 1 coin = $0.01 internally. Creator receives 90%, GIST keeps 10%.
-- Safe to run multiple times.

BEGIN;

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
);

DROP TRIGGER IF EXISTS trg_gist_coin_wallets_updated_at ON gist_coin_wallets;
CREATE TRIGGER trg_gist_coin_wallets_updated_at
BEFORE UPDATE ON gist_coin_wallets
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

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
);

ALTER TABLE gist_tip_transactions
DROP CONSTRAINT IF EXISTS ck_gist_tip_transactions_amount_exact_split;

CREATE INDEX IF NOT EXISTS idx_gist_tip_transactions_sender_created
ON gist_tip_transactions (sender_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_gist_tip_transactions_recipient_created
ON gist_tip_transactions (recipient_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_gist_tip_transactions_content_created
ON gist_tip_transactions (content_type, content_id, created_at DESC);

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
);

CREATE INDEX IF NOT EXISTS idx_gist_coin_transactions_user_created
ON gist_coin_transactions (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_gist_coin_transactions_reference
ON gist_coin_transactions (reference_type, reference_id)
WHERE reference_type IS NOT NULL AND reference_id IS NOT NULL;

-- RLS for Supabase/direct table access.
-- Backend service-role connections can still manage rows; users can only read their own data.
ALTER TABLE gist_coin_wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE gist_coin_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE gist_tip_transactions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS gist_coin_wallets_select_own ON gist_coin_wallets;
CREATE POLICY gist_coin_wallets_select_own
ON gist_coin_wallets
FOR SELECT
USING (
    user_id = NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
    OR user_id = NULLIF(auth.jwt() ->> 'gist_user_id', '')::BIGINT
);

DROP POLICY IF EXISTS gist_coin_transactions_select_own ON gist_coin_transactions;
CREATE POLICY gist_coin_transactions_select_own
ON gist_coin_transactions
FOR SELECT
USING (
    user_id = NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
    OR user_id = NULLIF(auth.jwt() ->> 'gist_user_id', '')::BIGINT
);

DROP POLICY IF EXISTS gist_tip_transactions_select_participant ON gist_tip_transactions;
CREATE POLICY gist_tip_transactions_select_participant
ON gist_tip_transactions
FOR SELECT
USING (
    sender_user_id = NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
    OR recipient_user_id = NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
    OR sender_user_id = NULLIF(auth.jwt() ->> 'gist_user_id', '')::BIGINT
    OR recipient_user_id = NULLIF(auth.jwt() ->> 'gist_user_id', '')::BIGINT
);

COMMIT;
