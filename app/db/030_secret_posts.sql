-- Migration 030: Add is_secret flag to posts (anonymous confessions)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS is_secret BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_posts_is_secret ON posts (is_secret) WHERE is_secret = TRUE;
