"""add failed_invites table

Revision ID: f5f6a7b8c9d0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS failed_invites (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            agent_id UUID,
            email VARCHAR(255) NOT NULL,
            full_name VARCHAR(255),
            role VARCHAR(50) NOT NULL,
            team_id UUID,
            invited_by UUID,
            reason VARCHAR(50) NOT NULL,
            failed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_failed_invites_email
        ON failed_invites(email);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_failed_invites_invited_by
        ON failed_invites(invited_by);
        """
    )

    if _is_supabase_connection(bind):
        op.execute("ALTER TABLE failed_invites ENABLE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS \"service_role_failed_invites_access\" ON failed_invites;")
        op.execute(
            """
            CREATE POLICY "service_role_failed_invites_access"
                ON failed_invites FOR ALL TO service_role
                USING (true)
                WITH CHECK (true);
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS failed_invites;")
