"""resolve orphaned pending actions and sync on approval delete

Revision ID: d6e7f8g9h0i1
Revises: c5d6e7f8g9h0
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d6e7f8g9h0i1"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8g9h0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One-time cleanup: resolve actions left at approval_status='pending' whose
    # approval request was deleted directly (no corresponding row left).
    op.execute(
        """
        UPDATE ai_agent_actions
        SET approval_status = 'rejected', dispatch_status = 'rejected'
        WHERE approval_status = 'pending'
          AND id NOT IN (SELECT action_id FROM ai_agent_approval_requests)
        """
    )

    # Safety net: if an approval request row is ever deleted directly (bypassing
    # the approve/reject endpoints), resolve the linked action instead of leaving
    # it stranded at approval_status='pending' forever.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION resolve_action_on_approval_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            UPDATE ai_agent_actions
            SET approval_status = 'rejected', dispatch_status = 'rejected'
            WHERE id = OLD.action_id AND approval_status = 'pending';
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_resolve_action_on_approval_delete
        BEFORE DELETE ON ai_agent_approval_requests
        FOR EACH ROW EXECUTE FUNCTION resolve_action_on_approval_delete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_resolve_action_on_approval_delete ON ai_agent_approval_requests")
    op.execute("DROP FUNCTION IF EXISTS resolve_action_on_approval_delete()")
