-- Add cover_image_url to voice_issues
-- Safe to run multiple times.

BEGIN;

ALTER TABLE voice_issues
    ADD COLUMN IF NOT EXISTS cover_image_url TEXT;

COMMIT;
