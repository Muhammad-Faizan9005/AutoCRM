"""enforce one team per sales rep

Revision ID: l4m5n6o7p8q9
Revises: k3l4m5n6o7p8
Create Date: 2026-05-30
"""

from typing import Sequence, Union

from alembic import op

revision: str = "l4m5n6o7p8q9"
down_revision: Union[str, Sequence[str], None] = "k3l4m5n6o7p8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
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
          AND ranked.rank > 1
        """
    )
    op.execute(
        """
        UPDATE agents a
        SET team_id = tm.team_id
        FROM team_members tm
        WHERE a.id = tm.agent_id
        """
    )
    op.execute(
        """
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
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE team_members DROP CONSTRAINT IF EXISTS unique_team_member_agent;")
