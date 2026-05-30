-- Migration: archive deleted users and deletion cleanup metadata
-- Date: 2026-05-30

BEGIN;

CREATE TABLE IF NOT EXISTS deleted_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID UNIQUE,
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    team_id UUID,
    permissions JSONB DEFAULT '{}'::jsonb,
    permission_file VARCHAR(255),
    deleted_by UUID REFERENCES agents(id) ON DELETE SET NULL,
    deleted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_deleted_users_agent_id ON deleted_users(agent_id);
CREATE INDEX IF NOT EXISTS idx_deleted_users_deleted_at ON deleted_users(deleted_at);

ALTER TABLE deleted_users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_role_deleted_users_access ON deleted_users;
CREATE POLICY service_role_deleted_users_access
    ON deleted_users FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

COMMIT;
