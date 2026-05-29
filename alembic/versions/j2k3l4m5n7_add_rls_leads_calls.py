"""add rls policies for crm access

Revision ID: j2k3l4m5n7
Revises: i1j2k3l4m5n6
Create Date: 2026-05-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "j2k3l4m5n7"
down_revision: Union[str, Sequence[str], None] = "i1j2k3l4m5n6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    bind = op.get_bind()
    if not _is_supabase_connection(bind):
        return

    op.execute("ALTER TABLE leads ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE call_sessions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE notes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE deals ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE call_room_tokens ENABLE ROW LEVEL SECURITY;")

    op.execute("DROP POLICY IF EXISTS leads_owner_manager_access ON leads;")
    op.execute("DROP POLICY IF EXISTS call_sessions_owner_manager_access ON call_sessions;")
    op.execute("DROP POLICY IF EXISTS tasks_owner_manager_access ON tasks;")
    op.execute("DROP POLICY IF EXISTS notes_owner_manager_access ON notes;")
    op.execute("DROP POLICY IF EXISTS deals_owner_manager_access ON deals;")
    op.execute("DROP POLICY IF EXISTS call_room_tokens_service_only ON call_room_tokens;")

    op.execute(
        """
        CREATE POLICY leads_owner_manager_access
            ON leads FOR ALL TO authenticated
            USING (
                owner_id = auth.uid()
                OR EXISTS (
                    SELECT 1
                    FROM team_members tm
                    JOIN teams t ON t.id = tm.team_id
                    WHERE tm.agent_id = leads.owner_id
                      AND t.manager_id = auth.uid()
                )
            )
            WITH CHECK (
                owner_id = auth.uid()
                OR EXISTS (
                    SELECT 1
                    FROM team_members tm
                    JOIN teams t ON t.id = tm.team_id
                    WHERE tm.agent_id = leads.owner_id
                      AND t.manager_id = auth.uid()
                )
            );
        """
    )

    op.execute(
        """
        CREATE POLICY call_sessions_owner_manager_access
            ON call_sessions FOR ALL TO authenticated
            USING (
                EXISTS (
                    SELECT 1
                    FROM leads l
                    WHERE l.id = call_sessions.lead_id
                      AND (
                        l.owner_id = auth.uid()
                        OR EXISTS (
                            SELECT 1
                            FROM team_members tm
                            JOIN teams t ON t.id = tm.team_id
                            WHERE tm.agent_id = l.owner_id
                              AND t.manager_id = auth.uid()
                        )
                      )
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1
                    FROM leads l
                    WHERE l.id = call_sessions.lead_id
                      AND (
                        l.owner_id = auth.uid()
                        OR EXISTS (
                            SELECT 1
                            FROM team_members tm
                            JOIN teams t ON t.id = tm.team_id
                            WHERE tm.agent_id = l.owner_id
                              AND t.manager_id = auth.uid()
                        )
                      )
                )
            );
        """
    )

    op.execute(
        """
        CREATE POLICY tasks_owner_manager_access
            ON tasks FOR ALL TO authenticated
            USING (
                entity_type <> 'lead'
                OR EXISTS (
                    SELECT 1
                    FROM leads l
                    WHERE l.id = tasks.entity_id
                      AND (
                        l.owner_id = auth.uid()
                        OR EXISTS (
                            SELECT 1
                            FROM team_members tm
                            JOIN teams t ON t.id = tm.team_id
                            WHERE tm.agent_id = l.owner_id
                              AND t.manager_id = auth.uid()
                        )
                      )
                )
            )
            WITH CHECK (
                entity_type <> 'lead'
                OR EXISTS (
                    SELECT 1
                    FROM leads l
                    WHERE l.id = tasks.entity_id
                      AND (
                        l.owner_id = auth.uid()
                        OR EXISTS (
                            SELECT 1
                            FROM team_members tm
                            JOIN teams t ON t.id = tm.team_id
                            WHERE tm.agent_id = l.owner_id
                              AND t.manager_id = auth.uid()
                        )
                      )
                )
            );
        """
    )

    op.execute(
        """
        CREATE POLICY notes_owner_manager_access
            ON notes FOR ALL TO authenticated
            USING (
                entity_type <> 'lead'
                OR EXISTS (
                    SELECT 1
                    FROM leads l
                    WHERE l.id = notes.entity_id
                      AND (
                        l.owner_id = auth.uid()
                        OR EXISTS (
                            SELECT 1
                            FROM team_members tm
                            JOIN teams t ON t.id = tm.team_id
                            WHERE tm.agent_id = l.owner_id
                              AND t.manager_id = auth.uid()
                        )
                      )
                )
            )
            WITH CHECK (
                entity_type <> 'lead'
                OR EXISTS (
                    SELECT 1
                    FROM leads l
                    WHERE l.id = notes.entity_id
                      AND (
                        l.owner_id = auth.uid()
                        OR EXISTS (
                            SELECT 1
                            FROM team_members tm
                            JOIN teams t ON t.id = tm.team_id
                            WHERE tm.agent_id = l.owner_id
                              AND t.manager_id = auth.uid()
                        )
                      )
                )
            );
        """
    )

    op.execute(
        """
        CREATE POLICY deals_owner_manager_access
            ON deals FOR ALL TO authenticated
            USING (
                owner_id = auth.uid()
                OR EXISTS (
                    SELECT 1
                    FROM team_members tm
                    JOIN teams t ON t.id = tm.team_id
                    WHERE tm.agent_id = deals.owner_id
                      AND t.manager_id = auth.uid()
                )
            )
            WITH CHECK (
                owner_id = auth.uid()
                OR EXISTS (
                    SELECT 1
                    FROM team_members tm
                    JOIN teams t ON t.id = tm.team_id
                    WHERE tm.agent_id = deals.owner_id
                      AND t.manager_id = auth.uid()
                )
            );
        """
    )

    op.execute(
        """
        CREATE POLICY call_room_tokens_service_only
            ON call_room_tokens FOR ALL
            USING (auth.role() = 'service_role')
            WITH CHECK (auth.role() = 'service_role');
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_supabase_connection(bind):
        return

    op.execute("DROP POLICY IF EXISTS call_room_tokens_service_only ON call_room_tokens;")
    op.execute("DROP POLICY IF EXISTS deals_owner_manager_access ON deals;")
    op.execute("DROP POLICY IF EXISTS notes_owner_manager_access ON notes;")
    op.execute("DROP POLICY IF EXISTS tasks_owner_manager_access ON tasks;")
    op.execute("DROP POLICY IF EXISTS call_sessions_owner_manager_access ON call_sessions;")
    op.execute("DROP POLICY IF EXISTS leads_owner_manager_access ON leads;")

    op.execute("ALTER TABLE call_room_tokens DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE deals DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE notes DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE tasks DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE call_sessions DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE leads DISABLE ROW LEVEL SECURITY;")
