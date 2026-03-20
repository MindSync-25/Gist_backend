-- Voice Feature Schema
-- Safe to run multiple times.

BEGIN;

-- -----------------------------------------------------------------------------
-- Voice Issues
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voice_issues (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(240) NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    tags TEXT,  -- comma-separated, e.g. "Trending,Politics,National"
    created_by_type VARCHAR(20) NOT NULL DEFAULT 'editorial'
        CHECK (created_by_type IN ('editorial', 'user')),
    created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived')),
    support_count INT NOT NULL DEFAULT 0,
    oppose_count INT NOT NULL DEFAULT 0,
    question_count INT NOT NULL DEFAULT 0,
    takes_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_issues_status ON voice_issues (status);
CREATE INDEX IF NOT EXISTS idx_voice_issues_is_featured ON voice_issues (is_featured);
CREATE INDEX IF NOT EXISTS idx_voice_issues_created_by_user ON voice_issues (created_by_user_id);

DROP TRIGGER IF EXISTS trg_voice_issues_updated_at ON voice_issues;
CREATE TRIGGER trg_voice_issues_updated_at
BEFORE UPDATE ON voice_issues
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- Voice Stances  (one stance per user per issue)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voice_stances (
    id BIGSERIAL PRIMARY KEY,
    issue_id BIGINT NOT NULL REFERENCES voice_issues(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stance VARCHAR(20) NOT NULL CHECK (stance IN ('support', 'oppose', 'question')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (issue_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_voice_stances_issue ON voice_stances (issue_id);
CREATE INDEX IF NOT EXISTS idx_voice_stances_user ON voice_stances (user_id);

DROP TRIGGER IF EXISTS trg_voice_stances_updated_at ON voice_stances;
CREATE TRIGGER trg_voice_stances_updated_at
BEFORE UPDATE ON voice_stances
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- Voice Takes  (comments on an issue)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voice_takes (
    id BIGSERIAL PRIMARY KEY,
    issue_id BIGINT NOT NULL REFERENCES voice_issues(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    parent_take_id BIGINT REFERENCES voice_takes(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    stance VARCHAR(20) CHECK (stance IN ('support', 'oppose', 'question')),
    reactions_count INT NOT NULL DEFAULT 0,
    replies_count INT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'published'
        CHECK (status IN ('published', 'hidden', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_takes_issue ON voice_takes (issue_id);
CREATE INDEX IF NOT EXISTS idx_voice_takes_user ON voice_takes (user_id);
CREATE INDEX IF NOT EXISTS idx_voice_takes_parent ON voice_takes (parent_take_id);

DROP TRIGGER IF EXISTS trg_voice_takes_updated_at ON voice_takes;
CREATE TRIGGER trg_voice_takes_updated_at
BEFORE UPDATE ON voice_takes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- Voice Polls
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voice_polls (
    id BIGSERIAL PRIMARY KEY,
    label VARCHAR(60) NOT NULL DEFAULT 'LIVE POLL',
    question VARCHAR(280) NOT NULL,
    issue_id BIGINT REFERENCES voice_issues(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    total_votes INT NOT NULL DEFAULT 0,
    closes_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_polls_is_active ON voice_polls (is_active);

DROP TRIGGER IF EXISTS trg_voice_polls_updated_at ON voice_polls;
CREATE TRIGGER trg_voice_polls_updated_at
BEFORE UPDATE ON voice_polls
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- Voice Poll Options
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voice_poll_options (
    id BIGSERIAL PRIMARY KEY,
    poll_id BIGINT NOT NULL REFERENCES voice_polls(id) ON DELETE CASCADE,
    label VARCHAR(140) NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    votes_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_poll_options_poll ON voice_poll_options (poll_id);

-- -----------------------------------------------------------------------------
-- Voice Poll Votes  (one vote per user per poll)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voice_poll_votes (
    id BIGSERIAL PRIMARY KEY,
    poll_id BIGINT NOT NULL REFERENCES voice_polls(id) ON DELETE CASCADE,
    option_id BIGINT NOT NULL REFERENCES voice_poll_options(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (poll_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_voice_poll_votes_poll ON voice_poll_votes (poll_id);
CREATE INDEX IF NOT EXISTS idx_voice_poll_votes_user ON voice_poll_votes (user_id);

COMMIT;
