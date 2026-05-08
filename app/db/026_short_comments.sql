-- Comments and reactions for shorts.
-- Mirrors the comic_comments / comic_comment_reactions pattern.

CREATE TABLE IF NOT EXISTS short_comments (
    id                BIGSERIAL PRIMARY KEY,
    short_id          BIGINT NOT NULL REFERENCES shorts(id) ON DELETE CASCADE,
    user_id           BIGINT REFERENCES users(id) ON DELETE SET NULL,
    parent_comment_id BIGINT REFERENCES short_comments(id) ON DELETE CASCADE,
    body              TEXT NOT NULL,
    status            VARCHAR(20) NOT NULL DEFAULT 'published',
    reactions_count   INT NOT NULL DEFAULT 0,
    replies_count     INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('published', 'hidden', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_short_comments_short_created ON short_comments (short_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_short_comments_parent ON short_comments (parent_comment_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_short_comments_user ON short_comments (user_id);

DROP TRIGGER IF EXISTS trg_short_comments_updated_at ON short_comments;
CREATE TRIGGER trg_short_comments_updated_at
BEFORE UPDATE ON short_comments
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS short_comment_reactions (
    id             BIGSERIAL PRIMARY KEY,
    comment_id     BIGINT NOT NULL REFERENCES short_comments(id) ON DELETE CASCADE,
    user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reaction_type  VARCHAR(20) NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (comment_id, user_id),
    CHECK (reaction_type IN ('like', 'fire', 'lol'))
);

CREATE INDEX IF NOT EXISTS idx_short_comment_reactions_comment ON short_comment_reactions (comment_id);
CREATE INDEX IF NOT EXISTS idx_short_comment_reactions_user ON short_comment_reactions (user_id);
