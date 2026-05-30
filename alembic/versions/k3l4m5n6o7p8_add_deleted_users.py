"""add deleted users archive

Revision ID: k3l4m5n6o7p8
Revises: j2k3l4m5n7
Create Date: 2026-05-30
"""

from typing import Sequence, Union

from alembic import op

revision: str = "k3l4m5n6o7p8"
down_revision: Union[str, Sequence[str], None] = "j2k3l4m5n7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
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
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_deleted_users_agent_id ON deleted_users(agent_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deleted_users_deleted_at ON deleted_users(deleted_at);")
    op.execute("ALTER TABLE deleted_users ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS service_role_deleted_users_access ON deleted_users;")
    op.execute(
        """
        CREATE POLICY service_role_deleted_users_access
            ON deleted_users FOR ALL TO service_role
            USING (true)
            WITH CHECK (true)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS deleted_users;")
