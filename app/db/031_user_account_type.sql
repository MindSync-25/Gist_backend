-- Add account type clarification for personal/professional profiles.

ALTER TABLE IF EXISTS users
ADD COLUMN IF NOT EXISTS account_type VARCHAR(20) NOT NULL DEFAULT 'personal';

UPDATE users
SET account_type = 'personal'
WHERE account_type IS NULL
   OR account_type NOT IN ('personal', 'professional');
