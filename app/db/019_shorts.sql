-- Unified shorts / video content table.
-- Holds ALL video content: pipeline-generated shorts AND user-uploaded videos.
-- source_type distinguishes origin; pipeline-specific columns are nullable for user uploads.

CREATE TABLE IF NOT EXISTS shorts (
    id                  BIGSERIAL PRIMARY KEY,

    -- Who created it (nullable for pipeline-generated content with no app user)
    author_user_id      BIGINT REFERENCES users(id) ON DELETE SET NULL,

    -- Origin of the video
    source_type         VARCHAR(30)  NOT NULL DEFAULT 'user_upload',

    -- Content metadata
    title               VARCHAR(180),
    description         TEXT         NOT NULL DEFAULT '',

    -- Video storage (Cloudflare R2)
    r2_object_key       TEXT,                       -- key inside the video bucket
    r2_public_url       TEXT,                       -- full accessible URL
    r2_bucket           VARCHAR(80),                -- e.g. gist-production-south-india
    thumbnail_url       TEXT,

    -- Video properties
    duration_seconds    FLOAT,
    aspect_ratio        NUMERIC(5, 2),              -- e.g. 0.56 for 9:16

    -- Music (nullable — not all videos have tracked BGM)
    music_track_id      BIGINT REFERENCES music_tracks(id) ON DELETE SET NULL,
    music_start_seconds FLOAT,                      -- offset used during render

    -- Social context (optional, used when video is associated with topic/character)
    topic_id            BIGINT REFERENCES topics(id) ON DELETE SET NULL,
    character_id        BIGINT REFERENCES characters(id) ON DELETE SET NULL,

    -- Pipeline-specific metadata (null for user uploads)
    pipeline_run_id     VARCHAR(80),                -- matches pipeline video_id (e.g. "1", "2")
    render_details      JSONB,                      -- full render metadata from pipeline

    -- Lifecycle
    status              VARCHAR(20)  NOT NULL DEFAULT 'draft',
    visibility          VARCHAR(20)  NOT NULL DEFAULT 'public',
    published_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CHECK (source_type IN ('pipeline_generated', 'user_upload', 'repost')),
    CHECK (status IN ('draft', 'processing', 'published', 'archived', 'deleted')),
    CHECK (visibility IN ('public', 'followers_only'))
);

-- Feed queries
CREATE INDEX IF NOT EXISTS idx_shorts_feed          ON shorts (status, published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_shorts_author        ON shorts (author_user_id, created_at DESC) WHERE author_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_shorts_topic         ON shorts (topic_id, published_at DESC) WHERE topic_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_shorts_character     ON shorts (character_id, published_at DESC) WHERE character_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_shorts_music         ON shorts (music_track_id) WHERE music_track_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_shorts_pipeline_run  ON shorts (pipeline_run_id) WHERE pipeline_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_shorts_source_type   ON shorts (source_type);

-- Auto-update updated_at
DROP TRIGGER IF EXISTS trg_shorts_updated_at ON shorts;
CREATE TRIGGER trg_shorts_updated_at
    BEFORE UPDATE ON shorts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
