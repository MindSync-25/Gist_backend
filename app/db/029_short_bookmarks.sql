-- Migration 029: short_bookmarks table + bookmarks_count on short_metrics

CREATE TABLE IF NOT EXISTS short_bookmarks (
    short_id   BIGINT NOT NULL REFERENCES shorts(id) ON DELETE CASCADE,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (short_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_short_bookmarks_user_id ON short_bookmarks (user_id);

ALTER TABLE short_metrics
    ADD COLUMN IF NOT EXISTS bookmarks_count INTEGER NOT NULL DEFAULT 0;
