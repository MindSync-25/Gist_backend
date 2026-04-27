-- Migration 025: Add cover_image_url to voice_polls
ALTER TABLE voice_polls
    ADD COLUMN IF NOT EXISTS cover_image_url TEXT;
