"""add customer and organization ownership

Revision ID: s5t6u7v8w9x0
Revises: r4s5t6u7v8w9
Create Date: 2026-06-26
"""

from alembic import op


revision = "s5t6u7v8w9x0"
down_revision = "r4s5t6u7v8w9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES agents(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES agents(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL")

    op.execute("CREATE INDEX IF NOT EXISTS idx_customers_owner_id ON customers(owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_customers_team_id ON customers(team_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_organizations_owner_id ON organizations(owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_organizations_team_id ON organizations(team_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_organizations_team_id")
    op.execute("DROP INDEX IF EXISTS idx_organizations_owner_id")
    op.execute("DROP INDEX IF EXISTS idx_customers_team_id")
    op.execute("DROP INDEX IF EXISTS idx_customers_owner_id")

    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS team_id")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS owner_id")
    op.execute("ALTER TABLE customers DROP COLUMN IF EXISTS team_id")
    op.execute("ALTER TABLE customers DROP COLUMN IF EXISTS owner_id")
