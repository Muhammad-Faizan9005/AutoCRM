"""add persistent frontdesk discovery and handoff state"""
from alembic import op

revision = "z3b4c5d6e7f8"
down_revision = "z2a3b4c5d6e7"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
    ALTER TABLE frontdesk_sessions
      ADD COLUMN IF NOT EXISTS mode VARCHAR(30) NOT NULL DEFAULT 'frontdesk',
      ADD COLUMN IF NOT EXISTS discovery_stage VARCHAR(40) NOT NULL DEFAULT 'greeting',
      ADD COLUMN IF NOT EXISTS identity_status VARCHAR(30) NOT NULL DEFAULT 'unknown',
      ADD COLUMN IF NOT EXISTS identity_confidence NUMERIC(5,4),
      ADD COLUMN IF NOT EXISTS handoff_status VARCHAR(30),
      ADD COLUMN IF NOT EXISTS handoff_assigned_to UUID REFERENCES agents(id) ON DELETE SET NULL,
      ADD COLUMN IF NOT EXISTS summary TEXT,
      ADD COLUMN IF NOT EXISTS discovery_facts JSONB NOT NULL DEFAULT '{}'::jsonb;
    ALTER TABLE frontdesk_appointments
      ADD COLUMN IF NOT EXISTS provider VARCHAR(30) NOT NULL DEFAULT 'cal.com',
      ADD COLUMN IF NOT EXISTS provider_uid VARCHAR(255),
      ADD COLUMN IF NOT EXISTS provider_event_id VARCHAR(255),
      ADD COLUMN IF NOT EXISTS meeting_url TEXT,
      ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
    CREATE TABLE IF NOT EXISTS frontdesk_handoffs (
      id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), session_id UUID NOT NULL REFERENCES frontdesk_sessions(id) ON DELETE CASCADE,
      reason TEXT NOT NULL, summary TEXT, urgency VARCHAR(20) NOT NULL DEFAULT 'normal',
      assigned_to UUID REFERENCES agents(id) ON DELETE SET NULL, status VARCHAR(30) NOT NULL DEFAULT 'open',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), resolved_at TIMESTAMPTZ);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_frontdesk_appointments_provider_uid ON frontdesk_appointments(provider, provider_uid) WHERE provider_uid IS NOT NULL;
    """)

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS frontdesk_handoffs")
