-- GIST Backend Initial Platform Schema
-- Safe to run multiple times.
-- This extends the existing image-pipeline tables (for example: comics).

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------------------------------------------------------
-- Shared utility: keep updated_at accurate on every UPDATE.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- Users and identity
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name VARCHAR(80) NOT NULL,
    bio TEXT,
    location VARCHAR(120),
    avatar_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_created_at ON users (created_at DESC);

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS follows (
    follower_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    followed_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (follower_user_id, followed_user_id),
    CHECK (follower_user_id <> followed_user_id)
);

CREATE INDEX IF NOT EXISTS idx_follows_followed ON follows (followed_user_id);

-- -----------------------------------------------------------------------------
-- Reference entities used across feed/voice/series
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS topics (
    id BIGSERIAL PRIMARY KEY,
    slug VARCHAR(40) NOT NULL UNIQUE,
    label VARCHAR(80) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_topics_sort_order ON topics (sort_order, id);

DROP TRIGGER IF EXISTS trg_topics_updated_at ON topics;
CREATE TRIGGER trg_topics_updated_at
BEFORE UPDATE ON topics
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS characters (
    id BIGSERIAL PRIMARY KEY,
    slug VARCHAR(40) NOT NULL UNIQUE,
    name VARCHAR(80) NOT NULL,
    handle VARCHAR(80) NOT NULL UNIQUE,
    role VARCHAR(120),
    bio TEXT,
    avatar_url TEXT,
    accent_color VARCHAR(20),
    followers_count INT NOT NULL DEFAULT 0,
    posts_count INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_characters_sort_order ON characters (sort_order, id);

DROP TRIGGER IF EXISTS trg_characters_updated_at ON characters;
CREATE TRIGGER trg_characters_updated_at
BEFORE UPDATE ON characters
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- Series
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS series (
    id BIGSERIAL PRIMARY KEY,
    slug VARCHAR(100) NOT NULL UNIQUE,
    title VARCHAR(180) NOT NULL,
    description TEXT,
    cover_image_url TEXT,
    created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    is_published BOOLEAN NOT NULL DEFAULT FALSE,
    followers_count INT NOT NULL DEFAULT 0,
    items_count INT NOT NULL DEFAULT 0,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_series_published ON series (is_published, published_at DESC);

DROP TRIGGER IF EXISTS trg_series_updated_at ON series;
CREATE TRIGGER trg_series_updated_at
BEFORE UPDATE ON series
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- Posts and engagement
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS posts (
    id BIGSERIAL PRIMARY KEY,
    source_type VARCHAR(20) NOT NULL DEFAULT 'native',
    comic_id INT REFERENCES comics(id) ON DELETE SET NULL,
    author_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    character_id BIGINT REFERENCES characters(id) ON DELETE SET NULL,
    topic_id BIGINT REFERENCES topics(id) ON DELETE SET NULL,
    series_id BIGINT REFERENCES series(id) ON DELETE SET NULL,
    title VARCHAR(180) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    image_url TEXT,
    image_aspect_ratio NUMERIC(5,2),
    format VARCHAR(20) NOT NULL DEFAULT 'hero',
    status VARCHAR(20) NOT NULL DEFAULT 'published',
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (source_type IN ('native', 'comic_pipeline')),
    CHECK (format IN ('hero', 'conversation', 'editorial', 'floating', 'magazine', 'immersive', 'x-thread')),
    CHECK (status IN ('draft', 'published', 'archived', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_posts_feed ON posts (status, published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_posts_topic ON posts (topic_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_character ON posts (character_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_series ON posts (series_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_source_comic ON posts (comic_id) WHERE comic_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_posts_updated_at ON posts;
CREATE TRIGGER trg_posts_updated_at
BEFORE UPDATE ON posts
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS post_metrics (
    post_id BIGINT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    likes_count INT NOT NULL DEFAULT 0,
    comments_count INT NOT NULL DEFAULT 0,
    shares_count INT NOT NULL DEFAULT 0,
    bookmarks_count INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS post_reactions (
    id BIGSERIAL PRIMARY KEY,
    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reaction_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (post_id, user_id),
    CHECK (reaction_type IN ('like', 'fire', 'lol'))
);

CREATE INDEX IF NOT EXISTS idx_post_reactions_post ON post_reactions (post_id);
CREATE INDEX IF NOT EXISTS idx_post_reactions_user ON post_reactions (user_id);

CREATE TABLE IF NOT EXISTS post_shares (
    id BIGSERIAL PRIMARY KEY,
    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    channel VARCHAR(30) NOT NULL DEFAULT 'native_share',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (channel IN ('copy_link', 'native_share', 'external_social', 'dm'))
);

CREATE INDEX IF NOT EXISTS idx_post_shares_post ON post_shares (post_id);
CREATE INDEX IF NOT EXISTS idx_post_shares_user ON post_shares (user_id);

CREATE TABLE IF NOT EXISTS bookmarks (
    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (post_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks (user_id);

CREATE TABLE IF NOT EXISTS comments (
    id BIGSERIAL PRIMARY KEY,
    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    parent_comment_id BIGINT REFERENCES comments(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'published',
    reactions_count INT NOT NULL DEFAULT 0,
    replies_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('published', 'hidden', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_comments_post_created ON comments (post_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments (parent_comment_id, created_at ASC);

DROP TRIGGER IF EXISTS trg_comments_updated_at ON comments;
CREATE TRIGGER trg_comments_updated_at
BEFORE UPDATE ON comments
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS comment_reactions (
    id BIGSERIAL PRIMARY KEY,
    comment_id BIGINT NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reaction_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (comment_id, user_id),
    CHECK (reaction_type IN ('like', 'fire', 'lol'))
);

CREATE INDEX IF NOT EXISTS idx_comment_reactions_comment ON comment_reactions (comment_id);

-- -----------------------------------------------------------------------------
-- Messaging
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id BIGSERIAL PRIMARY KEY,
    conversation_type VARCHAR(20) NOT NULL DEFAULT 'direct',
    title VARCHAR(140),
    created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    last_message_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (conversation_type IN ('direct', 'group'))
);

CREATE INDEX IF NOT EXISTS idx_conversations_last_message ON conversations (last_message_at DESC NULLS LAST, id DESC);

DROP TRIGGER IF EXISTS trg_conversations_updated_at ON conversations;
CREATE TRIGGER trg_conversations_updated_at
BEFORE UPDATE ON conversations
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS conversation_members (
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'member',
    is_muted BOOLEAN NOT NULL DEFAULT FALSE,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_read_at TIMESTAMPTZ,
    PRIMARY KEY (conversation_id, user_id),
    CHECK (role IN ('member', 'admin'))
);

CREATE INDEX IF NOT EXISTS idx_conversation_members_user ON conversation_members (user_id);

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    body TEXT,
    message_type VARCHAR(20) NOT NULL DEFAULT 'text',
    attachment_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    edited_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    CHECK (message_type IN ('text', 'image', 'system'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON messages (conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages (sender_user_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- Voice (stance + comments)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voice_issues (
    id BIGSERIAL PRIMARY KEY,
    slug VARCHAR(140) NOT NULL UNIQUE,
    title VARCHAR(220) NOT NULL,
    summary TEXT NOT NULL,
    category VARCHAR(60) NOT NULL,
    topic_id BIGINT REFERENCES topics(id) ON DELETE SET NULL,
    created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    support_count INT NOT NULL DEFAULT 0,
    oppose_count INT NOT NULL DEFAULT 0,
    question_count INT NOT NULL DEFAULT 0,
    takes_count INT NOT NULL DEFAULT 0,
    engagement_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    CHECK (status IN ('open', 'closed', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_voice_issues_status_created ON voice_issues (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_voice_issues_category_created ON voice_issues (category, created_at DESC);

DROP TRIGGER IF EXISTS trg_voice_issues_updated_at ON voice_issues;
CREATE TRIGGER trg_voice_issues_updated_at
BEFORE UPDATE ON voice_issues
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS voice_votes (
    issue_id BIGINT NOT NULL REFERENCES voice_issues(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stance VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (issue_id, user_id),
    CHECK (stance IN ('support', 'oppose', 'question'))
);

CREATE INDEX IF NOT EXISTS idx_voice_votes_user ON voice_votes (user_id, updated_at DESC);

DROP TRIGGER IF EXISTS trg_voice_votes_updated_at ON voice_votes;
CREATE TRIGGER trg_voice_votes_updated_at
BEFORE UPDATE ON voice_votes
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS voice_takes (
    id BIGSERIAL PRIMARY KEY,
    issue_id BIGINT NOT NULL REFERENCES voice_issues(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    stance VARCHAR(20) NOT NULL,
    body TEXT NOT NULL,
    upvotes_count INT NOT NULL DEFAULT 0,
    replies_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (stance IN ('support', 'oppose', 'question'))
);

CREATE INDEX IF NOT EXISTS idx_voice_takes_issue_created ON voice_takes (issue_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_voice_takes_user ON voice_takes (user_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_voice_takes_updated_at ON voice_takes;
CREATE TRIGGER trg_voice_takes_updated_at
BEFORE UPDATE ON voice_takes
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS voice_take_replies (
    id BIGSERIAL PRIMARY KEY,
    take_id BIGINT NOT NULL REFERENCES voice_takes(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    parent_reply_id BIGINT REFERENCES voice_take_replies(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_take_replies_take_created ON voice_take_replies (take_id, created_at ASC);

DROP TRIGGER IF EXISTS trg_voice_take_replies_updated_at ON voice_take_replies;
CREATE TRIGGER trg_voice_take_replies_updated_at
BEFORE UPDATE ON voice_take_replies
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- Series items and subscriptions
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS series_items (
    id BIGSERIAL PRIMARY KEY,
    series_id BIGINT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    post_id BIGINT REFERENCES posts(id) ON DELETE SET NULL,
    title VARCHAR(180) NOT NULL,
    summary TEXT,
    image_url TEXT,
    position INT NOT NULL,
    duration_seconds INT,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (series_id, position)
);

CREATE INDEX IF NOT EXISTS idx_series_items_series_published ON series_items (series_id, published_at DESC NULLS LAST, position ASC);

DROP TRIGGER IF EXISTS trg_series_items_updated_at ON series_items;
CREATE TRIGGER trg_series_items_updated_at
BEFORE UPDATE ON series_items
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS series_subscriptions (
    series_id BIGINT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscribed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    progress_item_id BIGINT REFERENCES series_items(id) ON DELETE SET NULL,
    progress_seconds INT NOT NULL DEFAULT 0,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (series_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_series_subscriptions_user ON series_subscriptions (user_id, subscribed_at DESC);

-- -----------------------------------------------------------------------------
-- Notifications
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id BIGSERIAL PRIMARY KEY,
    recipient_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    notification_type VARCHAR(40) NOT NULL,
    entity_type VARCHAR(40),
    entity_id BIGINT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ,
    CHECK (notification_type IN (
        'post_reaction',
        'post_comment',
        'comment_reply',
        'follow',
        'voice_vote',
        'voice_reply',
        'message',
        'series_update',
        'system'
    ))
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient_unread
    ON notifications (recipient_user_id, is_read, created_at DESC);

-- -----------------------------------------------------------------------------
-- Seed starter reference data used by frontend today.
-- -----------------------------------------------------------------------------
INSERT INTO topics (slug, label, description, sort_order)
VALUES
    ('all', 'For You', 'Personalized stories', 0),
    ('politics', 'Politics', 'Policy, governance and public affairs', 1),
    ('sports', 'Sports', 'Cricket and major sports events', 2),
    ('business', 'Business', 'Markets, jobs and economy', 3),
    ('tech', 'Tech', 'Technology and product trends', 4),
    ('entertainment', 'Entertainment', 'Cinema and culture', 5),
    ('world', 'World', 'Global stories and geopolitics', 6)
ON CONFLICT (slug) DO UPDATE
SET
    label = EXCLUDED.label,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE;

INSERT INTO characters (slug, name, handle, role, bio, avatar_url, accent_color, sort_order)
VALUES
    ('mira', 'Mira', '@miramicdrop', 'Policy Analyst', 'Policy + pop culture in one hot take.', 'https://i.pravatar.cc/300?img=47', '#6FA8FF', 1),
    ('bolt', 'Bolt', '@boltbites', 'Satire Host', 'Speedy satire, spicy facts.', 'https://i.pravatar.cc/300?img=12', '#FFB36A', 2),
    ('asha', 'Asha', '@asha_angle', 'Context Editor', 'Calm context before chaos.', 'https://i.pravatar.cc/300?img=32', '#F29CBC', 3),
    ('ledger', 'Ledger', '@ledgerlines', 'Business Decoder', 'Markets, budgets, and what they mean to your wallet.', 'https://i.pravatar.cc/300?img=15', '#8DBD8E', 4),
    ('raga', 'Raga', '@ragaroom', 'Culture Critic', 'Cinema, stars, and social mood in one frame.', 'https://i.pravatar.cc/300?img=5', '#A992FF', 5)
ON CONFLICT (slug) DO UPDATE
SET
    name = EXCLUDED.name,
    handle = EXCLUDED.handle,
    role = EXCLUDED.role,
    bio = EXCLUDED.bio,
    avatar_url = EXCLUDED.avatar_url,
    accent_color = EXCLUDED.accent_color,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE;

COMMIT;
