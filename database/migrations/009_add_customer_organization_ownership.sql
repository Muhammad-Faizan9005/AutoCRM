-- AutoCRM: record-level ownership for customers and organizations
-- Adds the scope fields used by RBAC visibility rules.

BEGIN;

ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES agents(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL;

ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES agents(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_customers_owner_id ON customers(owner_id);
CREATE INDEX IF NOT EXISTS idx_customers_team_id ON customers(team_id);
CREATE INDEX IF NOT EXISTS idx_organizations_owner_id ON organizations(owner_id);
CREATE INDEX IF NOT EXISTS idx_organizations_team_id ON organizations(team_id);

COMMIT;
