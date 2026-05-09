"""add teams and team_members tables

Revision ID: a1b2c3d4e5f6
Revises: 7a2c9c4d9b1f
Create Date: 2026-05-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'a1b2c3d4e5f6'
down_revision = '7a2c9c4d9b1f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. teams table
    op.create_table(
        'teams',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('uuid_generate_v4()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('manager_id', UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.UniqueConstraint('manager_id', name='unique_team_per_manager'),
    )

    # 2. team_members join table
    op.create_table(
        'team_members',
        sa.Column('team_id', UUID(as_uuid=True),
                  sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', UUID(as_uuid=True),
                  sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('joined_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('team_id', 'agent_id'),
    )

    # 3. team_id column on agents
    op.add_column(
        'agents',
        sa.Column('team_id', UUID(as_uuid=True),
                  sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
    )

    # 4. Indexes
    op.create_index('idx_teams_manager_id', 'teams', ['manager_id'])
    op.create_index('idx_team_members_team_id', 'team_members', ['team_id'])
    op.create_index('idx_team_members_agent_id', 'team_members', ['agent_id'])
    op.create_index('idx_agents_team_id', 'agents', ['team_id'])

    # 5. Update trigger for teams
    op.execute("""
        CREATE TRIGGER update_teams_updated_at
            BEFORE UPDATE ON teams
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # 6. RLS — enable row-level security on both new tables
    op.execute("ALTER TABLE teams ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE team_members ENABLE ROW LEVEL SECURITY;")

    # 7. RLS policies — authenticated users (matches existing pattern)
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

    # 8. RLS policies — service_role (backend operations)
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

    # 9. RLS policies — anon role (for pooler connections)
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
    # Drop policies first
    op.execute('DROP POLICY IF EXISTS "anon_team_members_access" ON team_members;')
    op.execute('DROP POLICY IF EXISTS "anon_teams_access" ON teams;')
    op.execute('DROP POLICY IF EXISTS "service_role_team_members_access" ON team_members;')
    op.execute('DROP POLICY IF EXISTS "service_role_teams_access" ON teams;')
    op.execute('DROP POLICY IF EXISTS "authenticated_team_members_access" ON team_members;')
    op.execute('DROP POLICY IF EXISTS "authenticated_teams_access" ON teams;')

    # Disable RLS
    op.execute("ALTER TABLE team_members DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE teams DISABLE ROW LEVEL SECURITY;")

    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS update_teams_updated_at ON teams;")

    # Drop indexes
    op.drop_index('idx_agents_team_id', table_name='agents')
    op.drop_index('idx_team_members_agent_id', table_name='team_members')
    op.drop_index('idx_team_members_team_id', table_name='team_members')
    op.drop_index('idx_teams_manager_id', table_name='teams')

    # Drop column and tables
    op.drop_column('agents', 'team_id')
    op.drop_table('team_members')
    op.drop_table('teams')
