-- Engagement metrics and reactions for shorts (pipeline-generated and user-uploaded videos).
-- Mirrors the structure of post_metrics / comic_metrics and post_reactions / comic_reactions.

-- Aggregate counters per short
CREATE TABLE IF NOT EXISTS short_metrics (
    short_id       BIGINT PRIMARY KEY REFERENCES shorts(id) ON DELETE CASCADE,
    likes_count    INT NOT NULL DEFAULT 0,
    comments_count INT NOT NULL DEFAULT 0,
    shares_count   INT NOT NULL DEFAULT 0,
    views_count    INT NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-user reactions on shorts
CREATE TABLE IF NOT EXISTS short_reactions (
    id             BIGSERIAL PRIMARY KEY,
    short_id       BIGINT NOT NULL REFERENCES shorts(id) ON DELETE CASCADE,
    user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reaction_type  VARCHAR(20) NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(short_id, user_id),
    CHECK (reaction_type IN ('like', 'fire', 'lol'))
);

CREATE INDEX IF NOT EXISTS idx_short_reactions_short ON short_reactions(short_id);
CREATE INDEX IF NOT EXISTS idx_short_reactions_user  ON short_reactions(user_id);

-- Backfill metric rows for all existing shorts (safe — ON CONFLICT is a no-op)
INSERT INTO short_metrics (short_id)
SELECT id FROM shorts
ON CONFLICT DO NOTHING;
