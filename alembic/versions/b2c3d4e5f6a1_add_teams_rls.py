"""add RLS policies for teams and team_members

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-05-09
"""
from alembic import op

revision = 'b2c3d4e5f6a1'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable RLS on both tables
    op.execute("ALTER TABLE teams ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE team_members ENABLE ROW LEVEL SECURITY;")

    # authenticated role policies (matches all other app tables)
    op.execute("""
        CREATE POLICY "authenticated_teams_access"
            ON teams FOR ALL TO authenticated
            USING (auth.role() = 'authenticated')
            WITH CHECK (auth.role() = 'authenticated');
    """)
    op.execute("""
        CREATE POLICY "authenticated_team_members_access"
            ON team_members FOR ALL TO authenticated
            USING (auth.role() = 'authenticated')
            WITH CHECK (auth.role() = 'authenticated');
    """)

    # service_role policies (backend direct operations)
    op.execute("""
        CREATE POLICY "service_role_teams_access"
            ON teams FOR ALL TO service_role
            USING (true)
            WITH CHECK (true);
    """)
    op.execute("""
        CREATE POLICY "service_role_team_members_access"
            ON team_members FOR ALL TO service_role
            USING (true)
            WITH CHECK (true);
    """)

    # anon role policies (Supabase pooler connects as anon/postgres)
    op.execute("""
        CREATE POLICY "anon_teams_access"
            ON teams FOR ALL TO anon
            USING (true)
            WITH CHECK (true);
    """)
    op.execute("""
        CREATE POLICY "anon_team_members_access"
            ON team_members FOR ALL TO anon
            USING (true)
            WITH CHECK (true);
    """)


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS "anon_team_members_access" ON team_members;')
    op.execute('DROP POLICY IF EXISTS "anon_teams_access" ON teams;')
    op.execute('DROP POLICY IF EXISTS "service_role_team_members_access" ON team_members;')
    op.execute('DROP POLICY IF EXISTS "service_role_teams_access" ON teams;')
    op.execute('DROP POLICY IF EXISTS "authenticated_team_members_access" ON team_members;')
    op.execute('DROP POLICY IF EXISTS "authenticated_teams_access" ON teams;')
    op.execute("ALTER TABLE team_members DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE teams DISABLE ROW LEVEL SECURITY;")
