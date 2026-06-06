"""add agent settings

Revision ID: n1o2p3q4r5s6
Revises: m1n2o3p4q5r6
Create Date: 2026-06-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "n1o2p3q4r5s6"
down_revision: Union[str, Sequence[str], None] = "m1n2o3p4q5r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    op.create_table(
        "ai_agent_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_type", sa.String(length=100), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.execute(
        """
        INSERT INTO ai_agent_settings (agent_type, enabled)
        VALUES
            ('lead_assistant', true),
            ('deal_risk_watcher', true),
            ('daily_summary_assistant', true)
        ON CONFLICT (agent_type) DO NOTHING;
        """
    )

    bind = op.get_bind()
    if _is_supabase_connection(bind):
        op.execute("ALTER TABLE ai_agent_settings ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE ai_agent_settings FORCE ROW LEVEL SECURITY;")
        op.execute(
            """
            CREATE POLICY "ai_agent_settings_service_role_access"
                ON ai_agent_settings FOR ALL TO service_role
                USING (true)
                WITH CHECK (true);
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _is_supabase_connection(bind):
        op.execute('DROP POLICY IF EXISTS "ai_agent_settings_service_role_access" ON ai_agent_settings;')
        op.execute("ALTER TABLE ai_agent_settings DISABLE ROW LEVEL SECURITY;")
    op.drop_table("ai_agent_settings")
