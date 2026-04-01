-- Comic localization metadata storage.
-- Safe to re-run.

BEGIN;

ALTER TABLE comics
    ADD COLUMN IF NOT EXISTS localized_copy JSONB;

COMMIT;
