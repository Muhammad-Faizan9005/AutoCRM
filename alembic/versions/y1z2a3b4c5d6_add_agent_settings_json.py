"""add agent settings json

Revision ID: y1z2a3b4c5d6
Revises: x0y1z2a3b4c5
Create Date: 2026-07-07
"""

from alembic import op


revision = "y1z2a3b4c5d6"
down_revision = "x0y1z2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        """
        UPDATE agents
        SET settings = jsonb_set(
            COALESCE(settings, '{}'::jsonb),
            '{developer_mode}',
            to_jsonb(COALESCE(developer_mode, false)),
            true
        )
        WHERE developer_mode IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.drop_column("agents", "settings")
