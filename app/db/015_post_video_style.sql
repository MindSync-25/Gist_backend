-- Migration 015: Add video_style column to posts for video filter/frame/overlay/trim metadata
ALTER TABLE posts ADD COLUMN IF NOT EXISTS video_style JSONB;
