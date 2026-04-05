"""add_password_hash_to_agents

Revision ID: 945b9872d621
Revises: 
Create Date: 2026-03-08 16:48:01.485926

"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '945b9872d621'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def _load_base_schema_sql(*, include_supabase_rls: bool) -> str:
    schema_file = Path(__file__).resolve().parents[2] / "database" / "schema.sql"
    schema_sql = schema_file.read_text(encoding="utf-8")

    if include_supabase_rls:
        return schema_sql

    rls_marker = "-- =============================================\n-- ROW LEVEL SECURITY (RLS)\n-- ============================================="
    if rls_marker in schema_sql:
        # Supabase roles/functions (authenticated, service_role, auth.*) are not available
        # on plain PostgreSQL and should not block base schema bootstrap.
        return schema_sql.split(rls_marker, 1)[0].rstrip() + "\n"

    return schema_sql


def upgrade() -> None:
    """Upgrade schema and ensure agents.password_hash exists."""
    bind = op.get_bind()
    inspector = inspect(bind)

    # Fresh database path: bootstrap full schema from repository SQL.
    if not inspector.has_table("agents"):
        bind.exec_driver_sql(
            _load_base_schema_sql(include_supabase_rls=_is_supabase_connection(bind))
        )
        return

    agent_columns = {column["name"] for column in inspector.get_columns("agents")}
    if "password_hash" in agent_columns:
        return

    op.add_column("agents", sa.Column("password_hash", sa.String(length=255), nullable=True))

    # Existing accounts must receive a forced-reset placeholder before NOT NULL enforcement.
    op.execute(
        """
        UPDATE agents
        SET password_hash = '__PASSWORD_RESET_REQUIRED__'
        WHERE password_hash IS NULL
        """
    )

    op.alter_column("agents", "password_hash", existing_type=sa.String(length=255), nullable=False)


def downgrade() -> None:
    """Downgrade schema - Remove password_hash column from agents table."""
    op.drop_column("agents", "password_hash")
