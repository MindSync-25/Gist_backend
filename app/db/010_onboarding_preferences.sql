-- Onboarding preferences: topic interests + multi-language selection.
-- Also replaces the vague "world" topic with "finance" (stock market / economy).
-- Safe to re-run.

-- 1. Replace world → finance topic
UPDATE topics SET slug = 'finance', label = 'Finance' WHERE slug = 'world';

-- 2. Add preferred topic slugs (filled during onboarding, min 3)
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS preferred_topic_slugs TEXT[] NOT NULL DEFAULT '{}';

-- 3. Add preferred languages: English is always included, user can add up to 2 more.
--    Stored as array e.g. '{en}' or '{en,hi}' or '{en,hi,te}'
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS preferred_languages TEXT[] NOT NULL DEFAULT '{en}';

-- 4. Track whether the user has completed onboarding (so returning users skip it)
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE;

-- Indexes for feed filtering by language
CREATE INDEX IF NOT EXISTS idx_users_preferred_languages ON users USING GIN (preferred_languages);
CREATE INDEX IF NOT EXISTS idx_users_preferred_topic_slugs ON users USING GIN (preferred_topic_slugs);
