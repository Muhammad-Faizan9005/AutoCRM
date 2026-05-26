"""add_password_reset_tokens

Revision ID: g1h2i3j4k5l6
Revises: f5f6a7b8c9d0
Create Date: 2026-05-26 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, Sequence[str], None] = "f5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            used_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id ON password_reset_tokens(user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_hash ON password_reset_tokens(token_hash);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires_at ON password_reset_tokens(expires_at);")

    if _is_supabase_connection(bind):
        op.execute("ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS \"authenticated_password_reset_tokens_access\" ON password_reset_tokens;")
        op.execute(
            """
            CREATE POLICY "authenticated_password_reset_tokens_access"
                ON password_reset_tokens FOR ALL TO authenticated
                USING (auth.role() = 'authenticated')
                WITH CHECK (auth.role() = 'authenticated');
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS password_reset_tokens;")
