-- Add Expo push token column to users for mobile push notifications.
-- Safe to re-run.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS expo_push_token TEXT;

CREATE INDEX IF NOT EXISTS idx_users_expo_push_token ON users (expo_push_token)
    WHERE expo_push_token IS NOT NULL;
