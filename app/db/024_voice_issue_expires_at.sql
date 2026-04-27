-- Add expires_at to voice_issues and an index for expiry queries.
-- Safe to run multiple times.

BEGIN;

ALTER TABLE voice_issues
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ DEFAULT NULL;

-- Partial index so the expiry sweep is fast (only non-null, open rows scanned).
CREATE INDEX IF NOT EXISTS ix_voice_issues_expires_at
    ON voice_issues (expires_at)
    WHERE expires_at IS NOT NULL AND status = 'open';

COMMIT;
