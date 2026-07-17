"""enable rls for task deadline alerts

Revision ID: c5d6e7f8g9h0
Revises: b4c5d6e7f8g9
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "c5d6e7f8g9h0"
down_revision = "b4c5d6e7f8g9"
branch_labels = None
depends_on = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    bind = op.get_bind()
    if not _is_supabase_connection(bind):
        return

    op.execute("ALTER TABLE task_deadline_alerts ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE task_deadline_alerts FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY "task_deadline_alerts_service_role_access"
            ON task_deadline_alerts FOR ALL TO service_role
            USING (true)
            WITH CHECK (true);
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_supabase_connection(bind):
        return

    op.execute('DROP POLICY IF EXISTS "task_deadline_alerts_service_role_access" ON task_deadline_alerts;')
    op.execute("ALTER TABLE task_deadline_alerts DISABLE ROW LEVEL SECURITY;")

