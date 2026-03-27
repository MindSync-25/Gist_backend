-- Comic-native social schema
-- Run in Supabase SQL editor.
-- Safe to re-run.

BEGIN;

-- -----------------------------------------------------------------------------
-- Comic metrics
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comic_metrics (
    comic_id BIGINT PRIMARY KEY REFERENCES comics(id) ON DELETE CASCADE,
    likes_count INT NOT NULL DEFAULT 0,
    comments_count INT NOT NULL DEFAULT 0,
    shares_count INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Comic reactions
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comic_reactions (
    id BIGSERIAL PRIMARY KEY,
    comic_id BIGINT NOT NULL REFERENCES comics(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reaction_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (comic_id, user_id),
    CHECK (reaction_type IN ('like', 'fire', 'lol'))
);

CREATE INDEX IF NOT EXISTS idx_comic_reactions_comic ON comic_reactions (comic_id);
CREATE INDEX IF NOT EXISTS idx_comic_reactions_user ON comic_reactions (user_id);

-- -----------------------------------------------------------------------------
-- Comic comments
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comic_comments (
    id BIGSERIAL PRIMARY KEY,
    comic_id BIGINT NOT NULL REFERENCES comics(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    parent_comment_id BIGINT REFERENCES comic_comments(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'published',
    reactions_count INT NOT NULL DEFAULT 0,
    replies_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('published', 'hidden', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_comic_comments_comic_created ON comic_comments (comic_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comic_comments_parent ON comic_comments (parent_comment_id, created_at ASC);

DROP TRIGGER IF EXISTS trg_comic_comments_updated_at ON comic_comments;
CREATE TRIGGER trg_comic_comments_updated_at
BEFORE UPDATE ON comic_comments
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- Comic comment reactions
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comic_comment_reactions (
    id BIGSERIAL PRIMARY KEY,
    comment_id BIGINT NOT NULL REFERENCES comic_comments(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reaction_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (comment_id, user_id),
    CHECK (reaction_type IN ('like', 'fire', 'lol'))
);

CREATE INDEX IF NOT EXISTS idx_comic_comment_reactions_comment ON comic_comment_reactions (comment_id);
CREATE INDEX IF NOT EXISTS idx_comic_comment_reactions_user ON comic_comment_reactions (user_id);

-- -----------------------------------------------------------------------------
-- Optional backfill from current comic_pipeline post-based social data.
-- This preserves existing engagement if you already used post-backed comic social.
-- -----------------------------------------------------------------------------
WITH latest_comic_posts AS (
    SELECT DISTINCT ON (p.comic_id)
        p.id AS post_id,
        p.comic_id
    FROM posts p
    WHERE p.source_type = 'comic_pipeline'
      AND p.comic_id IS NOT NULL
      AND p.status <> 'deleted'
    ORDER BY p.comic_id, p.published_at DESC, p.id DESC
)
INSERT INTO comic_metrics (comic_id, likes_count, comments_count, shares_count, updated_at)
SELECT
    lcp.comic_id,
    COALESCE(pm.likes_count, 0) AS likes_count,
    COALESCE(pm.comments_count, 0) AS comments_count,
    COALESCE(pm.shares_count, 0) AS shares_count,
    COALESCE(pm.updated_at, NOW()) AS updated_at
FROM latest_comic_posts lcp
LEFT JOIN post_metrics pm ON pm.post_id = lcp.post_id
ON CONFLICT (comic_id) DO UPDATE
SET
    likes_count = EXCLUDED.likes_count,
    comments_count = EXCLUDED.comments_count,
    shares_count = EXCLUDED.shares_count,
    updated_at = EXCLUDED.updated_at;

WITH latest_comic_posts AS (
    SELECT DISTINCT ON (p.comic_id)
        p.id AS post_id,
        p.comic_id
    FROM posts p
    WHERE p.source_type = 'comic_pipeline'
      AND p.comic_id IS NOT NULL
      AND p.status <> 'deleted'
    ORDER BY p.comic_id, p.published_at DESC, p.id DESC
)
INSERT INTO comic_comments (
    id,
    comic_id,
    user_id,
    parent_comment_id,
    body,
    status,
    reactions_count,
    replies_count,
    created_at,
    updated_at
)
SELECT
    c.id,
    lcp.comic_id,
    c.user_id,
    c.parent_comment_id,
    c.body,
    c.status,
    c.reactions_count,
    c.replies_count,
    c.created_at,
    c.updated_at
FROM comments c
JOIN latest_comic_posts lcp ON lcp.post_id = c.post_id
ON CONFLICT (id) DO NOTHING;

WITH latest_comic_posts AS (
    SELECT DISTINCT ON (p.comic_id)
        p.id AS post_id,
        p.comic_id
    FROM posts p
    WHERE p.source_type = 'comic_pipeline'
      AND p.comic_id IS NOT NULL
      AND p.status <> 'deleted'
    ORDER BY p.comic_id, p.published_at DESC, p.id DESC
)
INSERT INTO comic_comment_reactions (
    id,
    comment_id,
    user_id,
    reaction_type,
    created_at
)
SELECT
    cr.id,
    cr.comment_id,
    cr.user_id,
    cr.reaction_type,
    cr.created_at
FROM comment_reactions cr
JOIN comments c ON c.id = cr.comment_id
JOIN latest_comic_posts lcp ON lcp.post_id = c.post_id
ON CONFLICT (id) DO NOTHING;

WITH latest_comic_posts AS (
    SELECT DISTINCT ON (p.comic_id)
        p.id AS post_id,
        p.comic_id
    FROM posts p
    WHERE p.source_type = 'comic_pipeline'
      AND p.comic_id IS NOT NULL
      AND p.status <> 'deleted'
    ORDER BY p.comic_id, p.published_at DESC, p.id DESC
)
INSERT INTO comic_reactions (
    id,
    comic_id,
    user_id,
    reaction_type,
    created_at
)
SELECT
    pr.id,
    lcp.comic_id,
    pr.user_id,
    pr.reaction_type,
    pr.created_at
FROM post_reactions pr
JOIN latest_comic_posts lcp ON lcp.post_id = pr.post_id
ON CONFLICT (id) DO NOTHING;

-- Advance sequences after ID-preserving backfill.
SELECT setval(
    pg_get_serial_sequence('comic_comments', 'id'),
    COALESCE((SELECT MAX(id) FROM comic_comments), 1),
    (SELECT EXISTS (SELECT 1 FROM comic_comments))
);

SELECT setval(
    pg_get_serial_sequence('comic_comment_reactions', 'id'),
    COALESCE((SELECT MAX(id) FROM comic_comment_reactions), 1),
    (SELECT EXISTS (SELECT 1 FROM comic_comment_reactions))
);

SELECT setval(
    pg_get_serial_sequence('comic_reactions', 'id'),
    COALESCE((SELECT MAX(id) FROM comic_reactions), 1),
    (SELECT EXISTS (SELECT 1 FROM comic_reactions))
);

COMMIT;
