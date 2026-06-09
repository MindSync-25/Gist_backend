-- Migration 028: comic_bookmarks table + bookmarks_count on comic_metrics
-- Stores user bookmarks for comic posts (db-{id} on the frontend).

CREATE TABLE IF NOT EXISTS comic_bookmarks (
    comic_id  BIGINT NOT NULL REFERENCES comics(id) ON DELETE CASCADE,
    user_id   BIGINT NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (comic_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_comic_bookmarks_user_id ON comic_bookmarks (user_id);

ALTER TABLE comic_metrics
    ADD COLUMN IF NOT EXISTS bookmarks_count INTEGER NOT NULL DEFAULT 0;
