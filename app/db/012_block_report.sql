-- Migration 012: Block and Report tables

-- user_blocks: tracks users that a given user has blocked
CREATE TABLE IF NOT EXISTS user_blocks (
    blocker_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (blocker_user_id, blocked_user_id),
    CHECK (blocker_user_id <> blocked_user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_blocks_blocker ON user_blocks(blocker_user_id);
CREATE INDEX IF NOT EXISTS idx_user_blocks_blocked ON user_blocks(blocked_user_id);

-- reports: tracks user reports on posts, comments, or other users
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'report_entity_type') THEN
        CREATE TYPE report_entity_type AS ENUM ('post', 'comment', 'user');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'report_entity_type' AND e.enumlabel = 'comic_comment'
    ) THEN
        ALTER TYPE report_entity_type ADD VALUE 'comic_comment';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'report_reason') THEN
        CREATE TYPE report_reason AS ENUM ('spam', 'harassment', 'misinformation', 'nudity', 'hate_speech', 'other');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'report_status') THEN
        CREATE TYPE report_status AS ENUM ('pending', 'reviewed', 'actioned', 'dismissed');
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS reports (
    id               BIGSERIAL PRIMARY KEY,
    reporter_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    entity_type      report_entity_type NOT NULL,
    entity_id        BIGINT NOT NULL,
    reason           report_reason NOT NULL,
    detail           TEXT,
    status           report_status NOT NULL DEFAULT 'pending',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- one report per reporter per entity
    UNIQUE (reporter_user_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_reports_reporter ON reports(reporter_user_id);
CREATE INDEX IF NOT EXISTS idx_reports_entity   ON reports(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_reports_status   ON reports(status);
