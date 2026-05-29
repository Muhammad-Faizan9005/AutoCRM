"""add call sessions

Revision ID: i1j2k3l4m5n6
Revises: h2i3j4k5l6m7_add_status_change_logs_and_lead_loss_fields
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "i1j2k3l4m5n6"
down_revision = "h2i3j4k5l6m7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "call_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="SET NULL")),
        sa.Column("initiated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("room_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("direction", sa.String(length=20), nullable=False, server_default="outbound"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="created"),
        sa.Column("outcome", sa.String(length=100)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("recording_path", sa.Text()),
        sa.Column("recording_mime", sa.String(length=100)),
        sa.Column("recording_size", sa.Integer()),
        sa.Column("transcript", sa.Text()),
        sa.Column("processing_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("direction IN ('outbound', 'inbound')", name="ck_call_sessions_direction"),
        sa.CheckConstraint("status IN ('created', 'active', 'ended', 'failed')", name="ck_call_sessions_status"),
        sa.CheckConstraint("processing_status IN ('pending', 'processing', 'completed', 'failed')", name="ck_call_sessions_processing_status"),
    )

    op.create_table(
        "call_room_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("call_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issued_to", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("issued_to IN ('agent', 'lead')", name="ck_call_room_tokens_issued_to"),
    )

    op.create_index("idx_call_sessions_lead_id", "call_sessions", ["lead_id"])
    op.create_index("idx_call_sessions_started_at", "call_sessions", ["started_at"])
    op.create_index("idx_call_sessions_initiated_by", "call_sessions", ["initiated_by"])
    op.create_index("idx_call_room_tokens_call_id", "call_room_tokens", ["call_id"])
    op.create_index("idx_call_room_tokens_expires_at", "call_room_tokens", ["expires_at"])


def downgrade():
    op.drop_index("idx_call_room_tokens_expires_at", table_name="call_room_tokens")
    op.drop_index("idx_call_room_tokens_call_id", table_name="call_room_tokens")
    op.drop_index("idx_call_sessions_initiated_by", table_name="call_sessions")
    op.drop_index("idx_call_sessions_started_at", table_name="call_sessions")
    op.drop_index("idx_call_sessions_lead_id", table_name="call_sessions")
    op.drop_table("call_room_tokens")
    op.drop_table("call_sessions")
