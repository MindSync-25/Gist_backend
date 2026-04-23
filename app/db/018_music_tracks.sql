-- Music tracks catalog
-- Stores every BGM asset generated or uploaded to Cloudflare R2 gist-music bucket.

CREATE TABLE IF NOT EXISTS music_tracks (
    id              BIGSERIAL PRIMARY KEY,
    title           VARCHAR(180),
    prompt          TEXT,
    source_model    VARCHAR(80)  NOT NULL,          -- e.g. fal-ai/minimax-music/v2.5
    mood            VARCHAR(60),                    -- e.g. cinematic, upbeat, melancholic
    language_hint   VARCHAR(20),                    -- e.g. tamil, hindi, instrumental
    style_tags      JSONB,                          -- arbitrary tags array
    r2_object_key   TEXT         NOT NULL,          -- key inside gist-music bucket
    r2_public_url   TEXT         NOT NULL,          -- full accessible URL
    r2_bucket       VARCHAR(80)  NOT NULL DEFAULT 'gist-music',
    duration_seconds FLOAT,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_music_tracks_active      ON music_tracks (is_active, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_music_tracks_mood        ON music_tracks (mood) WHERE mood IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_music_tracks_lang        ON music_tracks (language_hint) WHERE language_hint IS NOT NULL;
