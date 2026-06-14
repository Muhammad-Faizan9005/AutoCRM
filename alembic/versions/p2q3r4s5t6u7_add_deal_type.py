"""add deal type to deals

Revision ID: p2q3r4s5t6u7
Revises: o1p2q3r4s5t6
Create Date: 2026-06-13
"""

from typing import Sequence, Union

from alembic import op


revision: str = "p2q3r4s5t6u7"
down_revision: Union[str, Sequence[str], None] = "o1p2q3r4s5t6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE deals ADD COLUMN IF NOT EXISTS deal_type VARCHAR(50) DEFAULT 'new_business'")
    op.execute("UPDATE deals SET deal_type = 'new_business' WHERE deal_type IS NULL OR deal_type = ''")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deals_deal_type ON deals(deal_type)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_deals_deal_type")
    op.execute("ALTER TABLE deals DROP COLUMN IF EXISTS deal_type")
