-- AutoCRM: backfill customer ownership for existing records.
-- Linked deals are the strongest source, with exact lead email match as a legacy fallback.

BEGIN;

ALTER TABLE deals
    ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customers(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_deals_customer_id ON deals(customer_id);

WITH deal_scope AS (
    SELECT DISTINCT ON (d.customer_id)
        d.customer_id,
        COALESCE(d.owner_id, l.owner_id) AS owner_id
    FROM deals d
    LEFT JOIN leads l ON l.id = d.lead_id
    WHERE d.customer_id IS NOT NULL
      AND COALESCE(d.owner_id, l.owner_id) IS NOT NULL
    ORDER BY d.customer_id, d.updated_at DESC NULLS LAST, d.created_at DESC NULLS LAST
)
UPDATE customers c
SET owner_id = deal_scope.owner_id,
    team_id = COALESCE(a.team_id, tm.team_id, c.team_id)
FROM deal_scope
LEFT JOIN agents a ON a.id = deal_scope.owner_id
LEFT JOIN team_members tm ON tm.agent_id = deal_scope.owner_id
WHERE c.id = deal_scope.customer_id
  AND c.owner_id IS NULL;

WITH lead_scope AS (
    SELECT DISTINCT ON (lower(l.email))
        lower(l.email) AS email_key,
        l.owner_id
    FROM leads l
    WHERE l.email IS NOT NULL
      AND l.owner_id IS NOT NULL
    ORDER BY lower(l.email), l.updated_at DESC NULLS LAST, l.created_at DESC NULLS LAST
)
UPDATE customers c
SET owner_id = lead_scope.owner_id,
    team_id = COALESCE(a.team_id, tm.team_id, c.team_id)
FROM lead_scope
LEFT JOIN agents a ON a.id = lead_scope.owner_id
LEFT JOIN team_members tm ON tm.agent_id = lead_scope.owner_id
WHERE lower(c.email) = lead_scope.email_key
  AND c.owner_id IS NULL;

COMMIT;
