-- Backend-managed sponsored campaigns
-- Run in Supabase SQL editor.
-- Safe to re-run.

BEGIN;

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
);

CREATE INDEX IF NOT EXISTS idx_sponsored_campaigns_feed_lookup
ON sponsored_campaigns (placement, is_active, priority, id DESC);

DROP TRIGGER IF EXISTS trg_sponsored_campaigns_updated_at ON sponsored_campaigns;
CREATE TRIGGER trg_sponsored_campaigns_updated_at
BEFORE UPDATE ON sponsored_campaigns
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- Sample records for immediate feed testing.
INSERT INTO sponsored_campaigns (
    name,
    placement,
    sponsor_name,
    headline,
    body,
    cta_label,
    target_url,
    priority,
    is_active,
    ad_network
) VALUES
(
    'Creator Suite Launch',
    'home_feed',
    'Gist Partner',
    'Creator tools that speed up your daily workflow',
    'Build better stories with templates, media kits, and AI caption assist in one place.',
    'Learn More',
    'https://example.com/sponsored/creator-tools',
    10,
    TRUE,
    'direct'
),
(
    'FinEdge Savings',
    'home_feed',
    'FinEdge',
    'Track spending and grow savings automatically',
    'See simple weekly insights and goals designed for young professionals.',
    'Try Now',
    'https://example.com/sponsored/finedge',
    20,
    TRUE,
    'direct'
)
ON CONFLICT DO NOTHING;

COMMIT;
