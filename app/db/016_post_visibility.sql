-- Migration 016: Add visibility controls for posts
ALTER TABLE posts ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) NOT NULL DEFAULT 'public';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_posts_visibility'
    ) THEN
        ALTER TABLE posts
            ADD CONSTRAINT ck_posts_visibility
            CHECK (visibility IN ('public', 'followers_only'));
    END IF;
END $$;
