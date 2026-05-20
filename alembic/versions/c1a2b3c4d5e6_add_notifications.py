"""add_notifications

Revision ID: c1a2b3c4d5e6
Revises: b2c3d4e5f6a1
Create Date: 2026-05-20 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            recipient_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            actor_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            type VARCHAR(50) NOT NULL,
            title VARCHAR(255) NOT NULL,
            message TEXT NOT NULL,
            entity_type VARCHAR(50),
            entity_id UUID,
            read_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_recipient_id ON notifications(recipient_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_read_at ON notifications(read_at);")

    if _is_supabase_connection(bind):
        op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS \"authenticated_notifications_access\" ON notifications;")
        op.execute(
            """
            CREATE POLICY "authenticated_notifications_access"
                ON notifications FOR ALL TO authenticated
                USING (auth.role() = 'authenticated')
                WITH CHECK (auth.role() = 'authenticated');
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications;")
