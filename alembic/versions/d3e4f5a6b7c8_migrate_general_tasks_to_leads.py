"""migrate general tasks to leads

Revision ID: d3e4f5a6b7c8
Revises: c1a2b3c4d5e6
Create Date: 2026-05-20

"""
from typing import Sequence, Union

from alembic import op


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        WITH latest_leads AS (
            SELECT
                l.id,
                l.owner_id,
                ROW_NUMBER() OVER (
                    PARTITION BY l.owner_id
                    ORDER BY l.created_at DESC
                ) AS rn
            FROM leads l
            WHERE l.owner_id IS NOT NULL
        )
        UPDATE tasks t
        SET
            entity_type = 'lead',
            entity_id = ll.id
        FROM latest_leads ll
        WHERE lower(t.entity_type) = 'general'
          AND t.assigned_to IS NOT NULL
          AND ll.owner_id = t.assigned_to
          AND ll.rn = 1;
        """
    )


def downgrade() -> None:
    # No safe automatic downgrade for data migrations.
    pass
