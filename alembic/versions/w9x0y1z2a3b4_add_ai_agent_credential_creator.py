"""add ai agent credential creator

Revision ID: w9x0y1z2a3b4
Revises: v8w9x0y1z2a3
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "w9x0y1z2a3b4"
down_revision = "v8w9x0y1z2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_agent_credentials",
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_ai_agent_creds_created_by",
        "ai_agent_credentials",
        ["created_by"],
    )


def downgrade() -> None:
    op.drop_index("idx_ai_agent_creds_created_by", table_name="ai_agent_credentials")
    op.drop_column("ai_agent_credentials", "created_by")
