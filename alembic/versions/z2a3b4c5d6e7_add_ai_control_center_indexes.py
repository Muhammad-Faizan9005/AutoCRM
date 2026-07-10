"""add ai control center query indexes

Revision ID: z2a3b4c5d6e7
Revises: y1z2a3b4c5d6
Create Date: 2026-07-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "y1z2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_ai_agent_runs_started_at", "ai_agent_runs", ["started_at"])
    op.create_index("idx_ai_agent_actions_created_at", "ai_agent_actions", ["created_at"])
    op.create_index("idx_ai_agent_approvals_state_created_at", "ai_agent_approval_requests", ["state", "created_at"])
    op.create_index("idx_ai_agents_display_name", "ai_agents", ["display_name"])


def downgrade() -> None:
    op.drop_index("idx_ai_agents_display_name", table_name="ai_agents")
    op.drop_index("idx_ai_agent_approvals_state_created_at", table_name="ai_agent_approval_requests")
    op.drop_index("idx_ai_agent_actions_created_at", table_name="ai_agent_actions")
    op.drop_index("idx_ai_agent_runs_started_at", table_name="ai_agent_runs")
