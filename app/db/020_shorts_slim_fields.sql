-- Add semantic metadata columns to shorts table.
-- Replaces the practice of storing verbose render_details blobs.
-- category and language come directly from the CSV/TopicRow input.
-- tags is a free-text array for search/filtering.

ALTER TABLE shorts
    ADD COLUMN IF NOT EXISTS category  VARCHAR(30),
    ADD COLUMN IF NOT EXISTS language  VARCHAR(30),
    ADD COLUMN IF NOT EXISTS tags      TEXT[];

CREATE INDEX IF NOT EXISTS idx_shorts_category ON shorts (category) WHERE category IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_shorts_language ON shorts (language) WHERE language IS NOT NULL;
