-- Add users.language expected by ORM/user APIs.
-- Safe to run multiple times.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS language VARCHAR(10);

UPDATE users
SET language = 'en'
WHERE language IS NULL;

ALTER TABLE users
    ALTER COLUMN language SET DEFAULT 'en';

ALTER TABLE users
    ALTER COLUMN language SET NOT NULL;
