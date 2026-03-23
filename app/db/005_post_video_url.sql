-- Migration 005: add video_url column for Shorts posts.
-- Safe to run multiple times.

BEGIN;

ALTER TABLE posts
    ADD COLUMN IF NOT EXISTS video_url TEXT;

COMMIT;
