"""formalize agent developer_mode column

Historically ``agents.developer_mode`` was created at request time by
``_ensure_profile_columns`` in the auth router (runtime DDL) rather than by a
migration. This migration formalizes the column so a fresh database has it
without relying on request-path DDL, which is being removed for performance.

The effective developer-mode value now lives in ``agents.settings`` JSON (see
migration y1z2a3b4c5d6); this legacy boolean column is retained for backward
compatibility and kept in sync as a mirror.

Revision ID: f8g9h0i1j2k3
Revises: e7f8g9h0i1j2
Create Date: 2026-07-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f8g9h0i1j2k3"
down_revision: Union[str, Sequence[str], None] = "e7f8g9h0i1j2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS developer_mode BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS developer_mode")
