-- Voice Live video rooms.

CREATE TABLE IF NOT EXISTS voice_live_sessions (
    id BIGSERIAL PRIMARY KEY,
    issue_id BIGINT NOT NULL REFERENCES voice_issues(id) ON DELETE CASCADE,
    host_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    room_slug VARCHAR(160) NOT NULL UNIQUE,
    provider VARCHAR(40) NOT NULL DEFAULT 'livekit',
    join_url TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    max_participants INTEGER NOT NULL DEFAULT 8,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_voice_live_sessions_status CHECK (status IN ('active', 'ended')),
    CONSTRAINT ck_voice_live_sessions_max_participants CHECK (max_participants BETWEEN 2 AND 8)
);

CREATE INDEX IF NOT EXISTS idx_voice_live_sessions_issue_status
    ON voice_live_sessions (issue_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_voice_live_sessions_host
    ON voice_live_sessions (host_user_id, created_at DESC)
    WHERE host_user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS voice_live_participants (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES voice_live_sessions(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'member',
    status VARCHAR(20) NOT NULL DEFAULT 'invited',
    invited_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    joined_at TIMESTAMPTZ,
    left_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_voice_live_participants_session_user UNIQUE (session_id, user_id),
    CONSTRAINT ck_voice_live_participants_role CHECK (role IN ('host', 'member')),
    CONSTRAINT ck_voice_live_participants_status CHECK (status IN ('invited', 'joined', 'left'))
);

CREATE INDEX IF NOT EXISTS idx_voice_live_participants_session_status
    ON voice_live_participants (session_id, status);

CREATE INDEX IF NOT EXISTS idx_voice_live_participants_user_created
    ON voice_live_participants (user_id, created_at DESC);
