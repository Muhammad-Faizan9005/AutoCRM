"""add ai metadata and meeting summary

Revision ID: q3r4s5t6u7v8
Revises: p2q3r4s5t6u7
Create Date: 2026-06-14
"""

from typing import Sequence, Union

from alembic import op

revision: str = "q3r4s5t6u7v8"
down_revision: Union[str, Sequence[str], None] = "p2q3r4s5t6u7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'manual'")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ai_reason TEXT")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ai_action_id UUID")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_ai_action_id ON tasks(ai_action_id)")
    op.execute("ALTER TABLE notes ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'manual'")
    op.execute("ALTER TABLE notes ADD COLUMN IF NOT EXISTS ai_reason TEXT")
    op.execute("ALTER TABLE notes ADD COLUMN IF NOT EXISTS ai_action_id UUID")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_source ON notes(source)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_ai_action_id ON notes(ai_action_id)")
    op.execute("ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS meeting_summary TEXT")

    op.execute(
        """
        UPDATE tasks t
        SET source='ai', ai_reason=aa.reason, ai_action_id=aa.id
        FROM ai_agent_actions aa
        WHERE aa.crm_record_type='task'
          AND aa.crm_record_id=t.id
          AND COALESCE(t.source,'manual') <> 'ai'
        """
    )
    op.execute(
        """
        UPDATE notes n
        SET source='ai', ai_reason=aa.reason, ai_action_id=aa.id
        FROM ai_agent_actions aa
        WHERE aa.crm_record_type='note'
          AND aa.crm_record_id=n.id
          AND COALESCE(n.source,'manual') <> 'ai'
        """
    )

def downgrade() -> None:
    op.execute("ALTER TABLE call_sessions DROP COLUMN IF EXISTS meeting_summary")
    op.execute("DROP INDEX IF EXISTS idx_notes_ai_action_id")
    op.execute("DROP INDEX IF EXISTS idx_notes_source")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS ai_action_id")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS ai_reason")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS source")
    op.execute("DROP INDEX IF EXISTS idx_tasks_ai_action_id")
    op.execute("DROP INDEX IF EXISTS idx_tasks_source")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS ai_action_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS ai_reason")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS source")
