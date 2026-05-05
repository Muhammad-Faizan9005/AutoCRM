"""add_agent_permissions

Revision ID: f0b9a0a3a4ce
Revises: 8c4fe2bde1f9
Create Date: 2026-05-05 06:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f0b9a0a3a4ce"
down_revision: Union[str, Sequence[str], None] = "8c4fe2bde1f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        """
        ALTER TABLE agents
        ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';
        """
    )

    op.execute(
        """
        UPDATE agents
        SET status = CASE WHEN is_active THEN 'active' ELSE 'disabled' END
        WHERE status IS NULL;
        """
    )

    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_status_check;")
    op.execute(
        """
        ALTER TABLE agents
        ADD CONSTRAINT agents_status_check
        CHECK (status IN ('active', 'invited', 'disabled'));
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_permissions (
            user_id UUID PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
            permissions JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_permissions_user_id ON agent_permissions(user_id);")

    op.execute("DROP TRIGGER IF EXISTS update_agent_permissions_updated_at ON agent_permissions;")
    op.execute(
        """
        CREATE TRIGGER update_agent_permissions_updated_at
            BEFORE UPDATE ON agent_permissions
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """
    )

    if _is_supabase_connection(bind):
        op.execute("ALTER TABLE agent_permissions ENABLE ROW LEVEL SECURITY;")
        op.execute(
            """
            DROP POLICY IF EXISTS "service_role_agent_permissions_access" ON agent_permissions;
            """
        )
        op.execute(
            """
            CREATE POLICY "service_role_agent_permissions_access"
                ON agent_permissions FOR ALL TO service_role
                USING (true)
                WITH CHECK (true);
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_permissions;")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_status_check;")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS status;")
