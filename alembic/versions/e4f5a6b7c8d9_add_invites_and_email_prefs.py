"""add invites and email preferences

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_invites (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            invited_by UUID REFERENCES agents(id) ON DELETE SET NULL,
            email VARCHAR(255) NOT NULL,
            role VARCHAR(50) NOT NULL,
            token_hash VARCHAR(64) NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            revoked_at TIMESTAMP WITH TIME ZONE,
            accepted_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_invites_token_hash
        ON agent_invites(token_hash);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_invites_agent_id
        ON agent_invites(agent_id);
        """
    )

    op.execute("DROP TRIGGER IF EXISTS update_agent_invites_updated_at ON agent_invites;")
    op.execute(
        """
        CREATE TRIGGER update_agent_invites_updated_at
            BEFORE UPDATE ON agent_invites
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_preferences (
            user_id UUID PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
            role VARCHAR(50) NOT NULL,
            email_enabled BOOLEAN DEFAULT true,
            lead_assigned_enabled BOOLEAN DEFAULT true,
            task_assigned_enabled BOOLEAN DEFAULT true,
            high_priority_override BOOLEAN DEFAULT true,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute("DROP TRIGGER IF EXISTS update_email_preferences_updated_at ON email_preferences;")
    op.execute(
        """
        CREATE TRIGGER update_email_preferences_updated_at
            BEFORE UPDATE ON email_preferences
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_logs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            event_type VARCHAR(50) NOT NULL,
            recipient_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            recipient_email VARCHAR(255) NOT NULL,
            status VARCHAR(20) NOT NULL,
            provider_message_id VARCHAR(255),
            payload JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_email_logs_recipient_id
        ON email_logs(recipient_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_email_logs_event_type
        ON email_logs(event_type);
        """
    )

    if _is_supabase_connection(bind):
        for table_name in ("agent_invites", "email_preferences", "email_logs"):
            op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")

        op.execute("DROP POLICY IF EXISTS \"service_role_agent_invites_access\" ON agent_invites;")
        op.execute(
            """
            CREATE POLICY "service_role_agent_invites_access"
                ON agent_invites FOR ALL TO service_role
                USING (true)
                WITH CHECK (true);
            """
        )

        op.execute("DROP POLICY IF EXISTS \"service_role_email_preferences_access\" ON email_preferences;")
        op.execute(
            """
            CREATE POLICY "service_role_email_preferences_access"
                ON email_preferences FOR ALL TO service_role
                USING (true)
                WITH CHECK (true);
            """
        )

        op.execute("DROP POLICY IF EXISTS \"service_role_email_logs_access\" ON email_logs;")
        op.execute(
            """
            CREATE POLICY "service_role_email_logs_access"
                ON email_logs FOR ALL TO service_role
                USING (true)
                WITH CHECK (true);
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS email_logs;")
    op.execute("DROP TABLE IF EXISTS email_preferences;")
    op.execute("DROP TABLE IF EXISTS agent_invites;")
