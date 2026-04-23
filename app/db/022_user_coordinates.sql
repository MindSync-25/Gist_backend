-- Add GPS coordinates to users for distance-based "In Your City" feed.
-- Safe to run multiple times (uses IF NOT EXISTS / idempotent ALTER).

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS latitude  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;

-- Partial index — only rows that actually have coordinates are indexed.
-- Used by the Haversine nearby query.
CREATE INDEX IF NOT EXISTS idx_users_coordinates
    ON users (latitude, longitude)
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
