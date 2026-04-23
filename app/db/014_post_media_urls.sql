-- Migration 014: Add media_urls column to posts for multi-image/video gallery support
ALTER TABLE posts ADD COLUMN IF NOT EXISTS media_urls JSONB;
