CREATE TABLE IF NOT EXISTS frontdesk_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), channel VARCHAR(30) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'active', contact_type VARCHAR(30), contact_id UUID,
    contact_name VARCHAR(255), contact_email VARCHAR(255), lead_owner_id UUID,
    intent VARCHAR(80), urgency VARCHAR(20), handoff_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS frontdesk_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), session_id UUID NOT NULL REFERENCES frontdesk_sessions(id) ON DELETE CASCADE,
    direction VARCHAR(20) NOT NULL, sender_type VARCHAR(30) NOT NULL, content TEXT NOT NULL,
    provider_message_id VARCHAR(255), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS frontdesk_appointments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), session_id UUID NOT NULL REFERENCES frontdesk_sessions(id) ON DELETE CASCADE,
    lead_id UUID, owner_id UUID, title VARCHAR(255) NOT NULL, notes TEXT, starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL, status VARCHAR(30) NOT NULL DEFAULT 'confirmed', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_frontdesk_sessions_status ON frontdesk_sessions(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_frontdesk_messages_session ON frontdesk_messages(session_id, created_at);
