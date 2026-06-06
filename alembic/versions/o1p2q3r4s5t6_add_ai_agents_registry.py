"""add ai agents registry and credentials

Revision ID: o1p2q3r4s5t6
Revises: n1o2p3q4r5s6
Create Date: 2026-06-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "o1p2q3r4s5t6"
down_revision: Union[str, Sequence[str], None] = "n1o2p3q4r5s6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_AI_AGENTS = [
    ("action_manager_agent",    "Action Manager Agent",      "Creates and dispatches playbook task actions.",        "action_manager"),
    ("lead_assistant",          "Lead Assistant",            "Monitors lead health and suggests follow-ups.",       "lead_assistant"),
    ("deal_risk_watcher",       "Deal Risk Watcher",         "Detects at-risk deals and triggers alerts.",          "deal_risk_watcher"),
    ("daily_summary_assistant", "Daily Summary Assistant",    "Produces end-of-day performance digests.",           "summary_assistant"),
    ("meeting_agent",           "Meeting Agent",             "Summarises completed meetings and creates actions.",  "meeting_assistant"),
]


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    # -- 1. ai_agents: identity registry ----------------------------------------
    op.create_table(
        "ai_agents",
        sa.Column("id",           postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_key",    sa.String(length=100), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description",  sa.Text()),
        sa.Column("agent_type",   sa.String(length=100), nullable=False),
        sa.Column("status",       sa.String(length=50),  nullable=False, server_default="active"),
        sa.Column("enabled",      sa.Boolean(),          nullable=False, server_default=sa.text("true")),
        sa.Column("capabilities", postgresql.JSONB(),    nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("config",       postgresql.JSONB(),    nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("service_url",  sa.Text()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at",   sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_ai_agents_agent_key", "ai_agents", ["agent_key"])
    op.create_index("idx_ai_agents_enabled",   "ai_agents", ["enabled"])

    # -- 2. ai_agent_credentials: hashed service tokens -------------------------
    op.create_table(
        "ai_agent_credentials",
        sa.Column("id",           postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("ai_agent_id",  postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ai_agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_prefix",   sa.String(length=20),  nullable=False),
        sa.Column("token_hash",   sa.String(length=256), nullable=False),
        sa.Column("scopes",       postgresql.JSONB(),    nullable=False,
                  server_default=sa.text(
                      """'["runs:create","runs:read","traces:create","actions:create","actions:read","settings:read"]'::jsonb"""
                  )),
        sa.Column("is_active",    sa.Boolean(),          nullable=False, server_default=sa.text("true")),
        sa.Column("expires_at",   sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("revoked_at",   sa.DateTime(timezone=True)),
    )
    op.create_index("idx_ai_agent_creds_agent",  "ai_agent_credentials", ["ai_agent_id"])
    op.create_index("idx_ai_agent_creds_active", "ai_agent_credentials", ["is_active"])

    # -- 3. seed default AI agents -----------------------------------------------
    for agent_key, display_name, description, agent_type in DEFAULT_AI_AGENTS:
        op.execute(
            f"""
            INSERT INTO ai_agents (agent_key, display_name, description, agent_type)
            VALUES ('{agent_key}', '{display_name}', '{description}', '{agent_type}')
            ON CONFLICT (agent_key) DO NOTHING;
            """
        )

    # -- 4. RLS for Supabase deployments ----------------------------------------
    bind = op.get_bind()
    if _is_supabase_connection(bind):
        for table in ("ai_agents", "ai_agent_credentials"):
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
        for table in ("ai_agent_credentials", "ai_agents"):
            op.execute(f'DROP POLICY IF EXISTS "{table}_service_role_access" ON {table};')
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_index("idx_ai_agent_creds_active",  table_name="ai_agent_credentials")
    op.drop_index("idx_ai_agent_creds_agent",   table_name="ai_agent_credentials")
    op.drop_table("ai_agent_credentials")
    op.drop_index("idx_ai_agents_enabled",  table_name="ai_agents")
    op.drop_index("idx_ai_agents_agent_key", table_name="ai_agents")
    op.drop_table("ai_agents")
