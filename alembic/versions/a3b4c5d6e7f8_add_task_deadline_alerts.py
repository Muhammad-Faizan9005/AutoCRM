"""add task deadline alerts

Revision ID: a3b4c5d6e7f8
Revises: z2a3b4c5d6e7
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a3b4c5d6e7f8"
down_revision = "z2a3b4c5d6e7"
branch_labels = None
depends_on = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    op.create_table(
        "task_deadline_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("dedupe_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("llm_cache_key", sa.String(length=255), nullable=True),
        sa.Column("llm_output", sa.Text(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_task_deadline_alerts_task_created", "task_deadline_alerts", ["task_id", "created_at"])
    op.create_index("idx_task_deadline_alerts_cache", "task_deadline_alerts", ["llm_cache_key"])
    bind = op.get_bind()
    if _is_supabase_connection(bind):
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
    if _is_supabase_connection(bind):
        op.execute('DROP POLICY IF EXISTS "task_deadline_alerts_service_role_access" ON task_deadline_alerts;')
        op.execute("ALTER TABLE task_deadline_alerts DISABLE ROW LEVEL SECURITY;")
    op.drop_index("idx_task_deadline_alerts_cache", table_name="task_deadline_alerts")
    op.drop_index("idx_task_deadline_alerts_task_created", table_name="task_deadline_alerts")
    op.drop_table("task_deadline_alerts")
