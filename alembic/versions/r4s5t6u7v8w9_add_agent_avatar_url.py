"""add agent avatar url

Revision ID: r4s5t6u7v8w9
Revises: q3r4s5t6u7v8
Create Date: 2026-06-17
"""

from alembic import op


revision = "r4s5t6u7v8w9"
down_revision = "q3r4s5t6u7v8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS avatar_url TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS avatar_url")
