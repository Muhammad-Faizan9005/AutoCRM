-- AutoCRM Database Schema
-- Run this in Supabase SQL Editor (SQL Editor tab in dashboard)

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================
-- CUSTOMERS TABLE
-- =============================================
CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    company VARCHAR(255),
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'lead', 'churned')),
    notes TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- TICKETS TABLE (Support/Service Requests)
-- =============================================
CREATE TABLE tickets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID REFERENCES customers(id) ON DELETE CASCADE,
    subject VARCHAR(500) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'pending', 'resolved', 'closed')),
    priority VARCHAR(20) DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    category VARCHAR(100),
    assigned_to UUID,
    ai_summary TEXT,
    ai_sentiment VARCHAR(50),
    ai_suggested_response TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE
);

-- =============================================
-- TICKET MESSAGES (Conversation Thread)
-- =============================================
CREATE TABLE ticket_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_id UUID REFERENCES tickets(id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL CHECK (sender_type IN ('customer', 'agent', 'ai')),
    sender_id UUID,
    content TEXT NOT NULL,
    attachments JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- AGENTS/USERS TABLE
-- =============================================
CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'sales_rep' CHECK (role IN ('admin', 'sales_manager', 'sales_rep')),
    is_active BOOLEAN DEFAULT true,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'invited', 'disabled')),
    team_id UUID,  -- FK added after teams table is created
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- AGENT PERMISSIONS TABLE
-- =============================================
CREATE TABLE agent_permissions (
    user_id UUID PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
    permission_file VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- TEAMS TABLE (one team per sales manager)
-- =============================================
CREATE TABLE teams (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    manager_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unique_team_per_manager UNIQUE (manager_id)
);

-- =============================================
-- TEAM MEMBERS JOIN TABLE
-- =============================================
CREATE TABLE team_members (
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (team_id, agent_id)
);

-- Add FK from agents.team_id -> teams.id
ALTER TABLE agents ADD CONSTRAINT fk_agents_team_id
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL;

-- =============================================
-- REVOKED TOKENS (JWT invalidation)
-- =============================================
CREATE TABLE revoked_tokens (
    token_hash VARCHAR(64) PRIMARY KEY,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- AI INTERACTIONS LOG (for analytics)
-- =============================================
CREATE TABLE ai_interactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_id UUID REFERENCES tickets(id) ON DELETE SET NULL,
    interaction_type VARCHAR(50) NOT NULL,
    prompt TEXT,
    response TEXT,
    model_used VARCHAR(100),
    tokens_used INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- ORGANIZATIONS TABLE
-- =============================================
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    website VARCHAR(255),
    industry VARCHAR(100),
    revenue NUMERIC(14, 2),
    address TEXT,
    phone VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- LEADS TABLE
-- =============================================
CREATE TABLE leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id UUID REFERENCES agents(id) ON DELETE SET NULL,
    organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    company VARCHAR(255),
    source VARCHAR(100),
    status VARCHAR(50) DEFAULT 'new',
    score INTEGER,
    score_reason TEXT,
    lost_reason TEXT,
    lost_notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- DEALS TABLE
-- =============================================
CREATE TABLE deals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lead_id UUID REFERENCES leads(id) ON DELETE SET NULL,
    owner_id UUID REFERENCES agents(id) ON DELETE SET NULL,
    organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
    stage VARCHAR(50) DEFAULT 'prospecting',
    value NUMERIC(14, 2),
    currency VARCHAR(10) DEFAULT 'USD',
    expected_close_at TIMESTAMP WITH TIME ZONE,
    lost_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- TASKS TABLE
-- =============================================
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    assigned_to UUID REFERENCES agents(id) ON DELETE SET NULL,
    status VARCHAR(50) DEFAULT 'open',
    priority VARCHAR(20) DEFAULT 'medium',
    due_at TIMESTAMP WITH TIME ZONE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- NOTES TABLE
-- =============================================
CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    author_id UUID REFERENCES agents(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- STATUS CHANGE LOGS
-- =============================================
CREATE TABLE status_change_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    old_status VARCHAR(50),
    new_status VARCHAR(50) NOT NULL,
    changed_by UUID REFERENCES agents(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- INDEXES FOR PERFORMANCE
-- =============================================
CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_customers_status ON customers(status);
CREATE INDEX idx_tickets_customer_id ON tickets(customer_id);
CREATE INDEX idx_tickets_status ON tickets(status);
CREATE INDEX idx_tickets_priority ON tickets(priority);
CREATE INDEX idx_tickets_created_at ON tickets(created_at DESC);
CREATE INDEX idx_ticket_messages_ticket_id ON ticket_messages(ticket_id);
CREATE INDEX idx_ai_interactions_ticket_id ON ai_interactions(ticket_id);
CREATE INDEX idx_revoked_tokens_expires_at ON revoked_tokens(expires_at);
CREATE INDEX idx_agent_permissions_user_id ON agent_permissions(user_id);
CREATE INDEX idx_organizations_name ON organizations(name);
CREATE INDEX idx_organizations_industry ON organizations(industry);
CREATE INDEX idx_leads_status ON leads(status);
CREATE INDEX idx_leads_owner_id ON leads(owner_id);
CREATE INDEX idx_leads_source ON leads(source);
CREATE INDEX idx_leads_created_at ON leads(created_at DESC);
CREATE INDEX idx_deals_stage ON deals(stage);
CREATE INDEX idx_deals_owner_id ON deals(owner_id);
CREATE INDEX idx_deals_organization_id ON deals(organization_id);
CREATE INDEX idx_deals_expected_close_at ON deals(expected_close_at);
CREATE INDEX idx_tasks_assigned_to ON tasks(assigned_to);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_due_at ON tasks(due_at);
CREATE INDEX idx_notes_entity_type ON notes(entity_type);
CREATE INDEX idx_notes_entity_id ON notes(entity_id);
CREATE INDEX idx_notes_author_id ON notes(author_id);
CREATE INDEX idx_notes_created_at ON notes(created_at DESC);
CREATE INDEX idx_status_change_logs_entity ON status_change_logs(entity_type, entity_id);
CREATE INDEX idx_status_change_logs_created_at ON status_change_logs(created_at DESC);
CREATE INDEX idx_teams_manager_id ON teams(manager_id);
CREATE INDEX idx_team_members_team_id ON team_members(team_id);
CREATE INDEX idx_team_members_agent_id ON team_members(agent_id);
CREATE INDEX idx_agents_team_id ON agents(team_id);

-- =============================================
-- UPDATE TIMESTAMP TRIGGER
-- =============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_customers_updated_at
    BEFORE UPDATE ON customers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tickets_updated_at
    BEFORE UPDATE ON tickets
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_agent_permissions_updated_at
    BEFORE UPDATE ON agent_permissions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_teams_updated_at
    BEFORE UPDATE ON teams
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_deals_updated_at
    BEFORE UPDATE ON deals
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_notes_updated_at
    BEFORE UPDATE ON notes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================
-- ROW LEVEL SECURITY (RLS)
-- =============================================
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticket_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_interactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE revoked_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_members ENABLE ROW LEVEL SECURITY;

-- App data tables are accessible only to authenticated users.
CREATE POLICY "authenticated_customers_access"
    ON customers FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_tickets_access"
    ON tickets FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_ticket_messages_access"
    ON ticket_messages FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_ai_interactions_access"
    ON ai_interactions FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_organizations_access"
    ON organizations FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_leads_access"
    ON leads FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_deals_access"
    ON deals FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_tasks_access"
    ON tasks FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_notes_access"
    ON notes FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_teams_access"
    ON teams FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_team_members_access"
    ON team_members FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

-- Agents can view/update their own profile when using Supabase Auth JWTs.
CREATE POLICY "agents_self_read"
    ON agents FOR SELECT TO authenticated
    USING (id = auth.uid());

CREATE POLICY "agents_self_update"
    ON agents FOR UPDATE TO authenticated
    USING (id = auth.uid())
    WITH CHECK (id = auth.uid());

-- Revocation table is intended for backend service usage.
CREATE POLICY "service_role_revoked_tokens_access"
    ON revoked_tokens FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_agent_permissions_access"
    ON agent_permissions FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_teams_access"
    ON teams FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_team_members_access"
    ON team_members FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- Anon role access for pooler connections
CREATE POLICY "anon_teams_access"
    ON teams FOR ALL TO anon
    USING (true)
    WITH CHECK (true);

CREATE POLICY "anon_team_members_access"
    ON team_members FOR ALL TO anon
    USING (true)
    WITH CHECK (true);
