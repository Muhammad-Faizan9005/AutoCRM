"""backfill deleted_users disabled status and revoked permissions

Revision ID: e7f8g9h0i1j2
Revises: d6e7f8g9h0i1
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e7f8g9h0i1j2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8g9h0i1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE deleted_users SET status = 'disabled' WHERE status <> 'disabled'")
    op.execute(
        """
        UPDATE deleted_users AS du
        SET permissions = sub.revoked
        FROM (
            SELECT id,
                   jsonb_object_agg(key, to_jsonb(false)) AS revoked
            FROM deleted_users, jsonb_object_keys(permissions) AS key
            GROUP BY id
        ) AS sub
        WHERE du.id = sub.id
          AND du.permissions <> sub.revoked
        """
    )


def downgrade() -> None:
    # Revoked permissions and disabled status cannot be restored; no-op.
    pass
