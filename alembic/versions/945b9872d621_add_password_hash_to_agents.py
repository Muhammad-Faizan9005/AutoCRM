"""add_password_hash_to_agents

Revision ID: 945b9872d621
Revises: 
Create Date: 2026-03-08 16:48:01.485926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '945b9872d621'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add password_hash column to agents table."""
    op.add_column("agents", sa.Column("password_hash", sa.String(length=255), nullable=True))

    # Existing accounts must receive a forced-reset placeholder before NOT NULL enforcement.
    op.execute(
        """
        UPDATE agents
        SET password_hash = '__PASSWORD_RESET_REQUIRED__'
        WHERE password_hash IS NULL
        """
    )

    op.alter_column("agents", "password_hash", existing_type=sa.String(length=255), nullable=False)


def downgrade() -> None:
    """Downgrade schema - Remove password_hash column from agents table."""
    op.drop_column("agents", "password_hash")
