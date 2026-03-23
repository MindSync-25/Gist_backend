-- Migration 004: add persisted image style payload for post image editor state.
-- Safe to run multiple times.

BEGIN;

ALTER TABLE posts
    ADD COLUMN IF NOT EXISTS image_style JSONB;

COMMIT;
