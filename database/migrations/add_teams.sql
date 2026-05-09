-- AutoCRM: Teams Feature Migration
-- Run this in the Supabase SQL Editor or via psql

-- =============================================
-- TEAMS TABLE (one team per manager)
-- =============================================
CREATE TABLE IF NOT EXISTS teams (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(255) NOT NULL,
    manager_id  UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unique_team_per_manager UNIQUE (manager_id)
);

-- =============================================
-- TEAM MEMBERS JOIN TABLE
-- =============================================
CREATE TABLE IF NOT EXISTS team_members (
    team_id     UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    joined_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (team_id, agent_id)
);

-- =============================================
-- ADD team_id COLUMN TO AGENTS (fast lookup)
-- =============================================
ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL;

-- =============================================
-- INDEXES
-- =============================================
CREATE INDEX IF NOT EXISTS idx_teams_manager_id     ON teams(manager_id);
CREATE INDEX IF NOT EXISTS idx_team_members_team_id  ON team_members(team_id);
CREATE INDEX IF NOT EXISTS idx_team_members_agent_id ON team_members(agent_id);
CREATE INDEX IF NOT EXISTS idx_agents_team_id        ON agents(team_id);

-- =============================================
-- UPDATE TRIGGER FOR teams
-- =============================================
CREATE TRIGGER update_teams_updated_at
    BEFORE UPDATE ON teams
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
