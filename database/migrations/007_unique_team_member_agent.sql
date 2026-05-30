-- Migration: enforce one team per sales rep
-- Date: 2026-05-30

BEGIN;

WITH ranked_members AS (
    SELECT
        ctid,
        agent_id,
        team_id,
        ROW_NUMBER() OVER (
            PARTITION BY agent_id
            ORDER BY joined_at DESC, team_id DESC
        ) AS rank
    FROM team_members
)
DELETE FROM team_members tm
USING ranked_members ranked
WHERE tm.ctid = ranked.ctid
  AND ranked.rank > 1;

UPDATE agents a
SET team_id = tm.team_id
FROM team_members tm
WHERE a.id = tm.agent_id;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'unique_team_member_agent'
    ) THEN
        ALTER TABLE team_members
        ADD CONSTRAINT unique_team_member_agent UNIQUE (agent_id);
    END IF;
END $$;

COMMIT;
