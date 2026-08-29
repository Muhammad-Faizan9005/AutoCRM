"""merge all migration heads

Revision ID: 1f02838263db
Revises: f8g9h0i1j2k3, z3b4c5d6e7f8
Create Date: 2026-08-28 00:04:25.322337

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1f02838263db'
down_revision: Union[str, Sequence[str], None] = ('f8g9h0i1j2k3', 'z3b4c5d6e7f8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
