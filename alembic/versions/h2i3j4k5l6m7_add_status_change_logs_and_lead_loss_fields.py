"""add_status_change_logs_and_lead_loss_fields

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-06-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "h2i3j4k5l6m7"
down_revision: Union[str, Sequence[str], None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    bind = op.get_bind()

    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS lost_reason TEXT;")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS lost_notes TEXT;")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS status_change_logs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            entity_type VARCHAR(50) NOT NULL,
            entity_id UUID NOT NULL,
            old_status VARCHAR(50),
            new_status VARCHAR(50) NOT NULL,
            changed_by UUID REFERENCES agents(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_status_change_logs_entity ON status_change_logs(entity_type, entity_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_status_change_logs_created_at ON status_change_logs(created_at DESC);"
    )

    if _is_supabase_connection(bind):
        op.execute("ALTER TABLE status_change_logs ENABLE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS \"authenticated_status_change_logs_access\" ON status_change_logs;")
        op.execute(
            """
            CREATE POLICY \"authenticated_status_change_logs_access\"
                ON status_change_logs FOR ALL TO authenticated
                USING (auth.role() = 'authenticated')
                WITH CHECK (auth.role() = 'authenticated');
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS status_change_logs;")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS lost_reason;")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS lost_notes;")
