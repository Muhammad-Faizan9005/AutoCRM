-- Migration: harden RLS and add persistent JWT revocation storage
-- Date: 2026-04-03

BEGIN;

CREATE TABLE IF NOT EXISTS revoked_tokens (
    token_hash VARCHAR(64) PRIMARY KEY,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires_at ON revoked_tokens(expires_at);

ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticket_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_interactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE revoked_tokens ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow all for authenticated users" ON customers;
DROP POLICY IF EXISTS "Allow all for authenticated users" ON tickets;
DROP POLICY IF EXISTS "Allow all for authenticated users" ON ticket_messages;
DROP POLICY IF EXISTS "Allow all for authenticated users" ON agents;
DROP POLICY IF EXISTS "Allow all for authenticated users" ON ai_interactions;

DROP POLICY IF EXISTS authenticated_customers_access ON customers;
DROP POLICY IF EXISTS authenticated_tickets_access ON tickets;
DROP POLICY IF EXISTS authenticated_ticket_messages_access ON ticket_messages;
DROP POLICY IF EXISTS authenticated_ai_interactions_access ON ai_interactions;
DROP POLICY IF EXISTS agents_self_read ON agents;
DROP POLICY IF EXISTS agents_self_update ON agents;
DROP POLICY IF EXISTS service_role_revoked_tokens_access ON revoked_tokens;

CREATE POLICY authenticated_customers_access
    ON customers FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY authenticated_tickets_access
    ON tickets FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY authenticated_ticket_messages_access
    ON ticket_messages FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY authenticated_ai_interactions_access
    ON ai_interactions FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY agents_self_read
    ON agents FOR SELECT TO authenticated
    USING (id = auth.uid());

CREATE POLICY agents_self_update
    ON agents FOR UPDATE TO authenticated
    USING (id = auth.uid())
    WITH CHECK (id = auth.uid());

CREATE POLICY service_role_revoked_tokens_access
    ON revoked_tokens FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

COMMIT;
