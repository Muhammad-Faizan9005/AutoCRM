"""make ai credentials service scoped

Revision ID: x0y1z2a3b4c5
Revises: w9x0y1z2a3b4
Create Date: 2026-07-07
"""

from alembic import op
from sqlalchemy.dialects import postgresql


revision = "x0y1z2a3b4c5"
down_revision = "w9x0y1z2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ai_agent_credentials",
        "ai_agent_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("DELETE FROM ai_agent_credentials WHERE ai_agent_id IS NULL")
    op.alter_column(
        "ai_agent_credentials",
        "ai_agent_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
