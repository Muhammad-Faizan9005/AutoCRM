"""relabel deal risk approval notifications

Revision ID: v8w9x0y1z2a3
Revises: u7v8w9x0y1z2
Create Date: 2026-07-06
"""

from alembic import op


revision = "v8w9x0y1z2a3"
down_revision = "u7v8w9x0y1z2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE notifications
        SET
            type = 'agent_alert',
            title = 'Deal risk alert',
            message = 'Deal risk detected. Review stage progress, recent activity, owner follow-up, and next steps.'
        WHERE type = 'agent_approval'
          AND entity_type = 'deal'
          AND title = 'AI approval required: Deal risk alert'
          AND message LIKE 'Deal risk detected Review approval #%';
        """
    )


def downgrade() -> None:
    pass
