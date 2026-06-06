"""add agent control plane tables

Revision ID: m1n2o3p4q5r6
Revises: l4m5n6o7p8q9
Create Date: 2026-06-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "m1n2o3p4q5r6"
down_revision: Union[str, Sequence[str], None] = "l4m5n6o7p8q9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

    op.create_table(
        "ai_agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("external_run_id", postgresql.UUID(as_uuid=True), unique=True),
        sa.Column("trigger_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="running"),
        sa.Column("event_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("plan_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", sa.Text()),
        sa.Column("failure_cause", sa.String(length=100)),
        sa.Column("failure_detail", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_ai_agent_runs_entity", "ai_agent_runs", ["entity_id", "entity_type"])
    op.create_index("idx_ai_agent_runs_status", "ai_agent_runs", ["status"])

    op.create_table(
        "ai_agent_run_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_agent_runs.id", ondelete="CASCADE")),
        sa.Column("external_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("step", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="completed"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_ai_agent_run_traces_run", "ai_agent_run_traces", ["run_id", "created_at"])

    op.create_table(
        "ai_agent_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_agent_runs.id", ondelete="SET NULL")),
        sa.Column("external_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("idempotency_key", sa.String(length=128), unique=True),
        sa.Column("approval_status", sa.String(length=50), nullable=False, server_default="auto_approved"),
        sa.Column("dispatch_status", sa.String(length=50), nullable=False, server_default="not_dispatched"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("crm_record_type", sa.String(length=50)),
        sa.Column("crm_record_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_ai_agent_actions_entity", "ai_agent_actions", ["entity_id", "entity_type"])
    op.create_index("idx_ai_agent_actions_approval", "ai_agent_actions", ["approval_status"])

    op.create_table(
        "ai_agent_approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_agent_actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("approver_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("reason", sa.Text()),
        sa.Column("approver_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_ai_agent_approvals_state", "ai_agent_approval_requests", ["state"])

    bind = op.get_bind()
    if _is_supabase_connection(bind):
        for table in [
            "ai_agent_runs",
            "ai_agent_run_traces",
            "ai_agent_actions",
            "ai_agent_approval_requests",
        ]:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
            op.execute(
                f"""
                CREATE POLICY "{table}_service_role_access"
                    ON {table} FOR ALL TO service_role
                    USING (true)
                    WITH CHECK (true);
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    if _is_supabase_connection(bind):
        for table in [
            "ai_agent_approval_requests",
            "ai_agent_actions",
            "ai_agent_run_traces",
            "ai_agent_runs",
        ]:
            op.execute(f'DROP POLICY IF EXISTS "{table}_service_role_access" ON {table};')
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_index("idx_ai_agent_approvals_state", table_name="ai_agent_approval_requests")
    op.drop_table("ai_agent_approval_requests")
    op.drop_index("idx_ai_agent_actions_approval", table_name="ai_agent_actions")
    op.drop_index("idx_ai_agent_actions_entity", table_name="ai_agent_actions")
    op.drop_table("ai_agent_actions")
    op.drop_index("idx_ai_agent_run_traces_run", table_name="ai_agent_run_traces")
    op.drop_table("ai_agent_run_traces")
    op.drop_index("idx_ai_agent_runs_status", table_name="ai_agent_runs")
    op.drop_index("idx_ai_agent_runs_entity", table_name="ai_agent_runs")
    op.drop_table("ai_agent_runs")
