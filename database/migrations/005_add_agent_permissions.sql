-- Migration: add agent permissions and status
-- Date: 2026-05-05

BEGIN;

ALTER TABLE agents ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';
UPDATE agents
SET status = CASE WHEN is_active THEN 'active' ELSE 'disabled' END
WHERE status IS NULL;
ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_status_check;
ALTER TABLE agents ADD CONSTRAINT agents_status_check
CHECK (status IN ('active', 'invited', 'disabled'));

CREATE TABLE IF NOT EXISTS agent_permissions (
    user_id UUID PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
    permission_file VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_permissions_user_id ON agent_permissions(user_id);

DROP TRIGGER IF EXISTS update_agent_permissions_updated_at ON agent_permissions;
CREATE TRIGGER update_agent_permissions_updated_at
    BEFORE UPDATE ON agent_permissions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE agent_permissions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_role_agent_permissions_access ON agent_permissions;
CREATE POLICY service_role_agent_permissions_access
    ON agent_permissions FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

COMMIT;
