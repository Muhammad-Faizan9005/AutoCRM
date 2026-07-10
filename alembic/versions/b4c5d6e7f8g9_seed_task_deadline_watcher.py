"""seed task deadline watcher agent

Revision ID: b4c5d6e7f8g9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "b4c5d6e7f8g9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO ai_agents (agent_key, display_name, description, agent_type, status, enabled)
        VALUES (
            'task_deadline_watcher',
            'Task Deadline Watcher',
            'Monitors due and overdue tasks, escalates risk, and drafts internal recovery guidance.',
            'task_deadline_watcher',
            'active',
            true
        )
        ON CONFLICT (agent_key) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            description = EXCLUDED.description,
            agent_type = EXCLUDED.agent_type,
            status = EXCLUDED.status,
            enabled = COALESCE(ai_agents.enabled, EXCLUDED.enabled),
            updated_at = NOW();
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM ai_agents WHERE agent_key = 'task_deadline_watcher';")

