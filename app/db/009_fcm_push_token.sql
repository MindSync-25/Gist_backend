-- Add FCM push token column to users for direct Firebase push notifications.
-- Safe to re-run.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS fcm_push_token TEXT;

CREATE INDEX IF NOT EXISTS idx_users_fcm_push_token ON users (fcm_push_token)
    WHERE fcm_push_token IS NOT NULL;
