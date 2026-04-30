"""add_crm_entities

Revision ID: 8c4fe2bde1f9
Revises: 945b9872d621
Create Date: 2026-04-30 19:45:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "8c4fe2bde1f9"
down_revision: Union[str, Sequence[str], None] = "945b9872d621"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name VARCHAR(255) NOT NULL,
            website VARCHAR(255),
            industry VARCHAR(100),
            revenue NUMERIC(14, 2),
            address TEXT,
            phone VARCHAR(50),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            owner_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            phone VARCHAR(50),
            company VARCHAR(255),
            source VARCHAR(100),
            status VARCHAR(50) DEFAULT 'new',
            score INTEGER,
            score_reason TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS deals (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            lead_id UUID REFERENCES leads(id) ON DELETE SET NULL,
            owner_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
            stage VARCHAR(50) DEFAULT 'prospecting',
            value NUMERIC(14, 2),
            currency VARCHAR(10) DEFAULT 'USD',
            expected_close_at TIMESTAMP WITH TIME ZONE,
            lost_reason TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            entity_type VARCHAR(50) NOT NULL,
            entity_id UUID NOT NULL,
            assigned_to UUID REFERENCES agents(id) ON DELETE SET NULL,
            status VARCHAR(50) DEFAULT 'open',
            priority VARCHAR(20) DEFAULT 'medium',
            due_at TIMESTAMP WITH TIME ZONE,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            entity_type VARCHAR(50) NOT NULL,
            entity_id UUID NOT NULL,
            author_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_organizations_name ON organizations(name);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_organizations_industry ON organizations(industry);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_owner_id ON leads(owner_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deals_owner_id ON deals(owner_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deals_organization_id ON deals(organization_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deals_expected_close_at ON deals(expected_close_at);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks(assigned_to);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_entity_type ON notes(entity_type);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_entity_id ON notes(entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_author_id ON notes(author_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at DESC);")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
        """
    )

    op.execute("DROP TRIGGER IF EXISTS update_organizations_updated_at ON organizations;")
    op.execute(
        """
        CREATE TRIGGER update_organizations_updated_at
            BEFORE UPDATE ON organizations
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """
    )

    op.execute("DROP TRIGGER IF EXISTS update_leads_updated_at ON leads;")
    op.execute(
        """
        CREATE TRIGGER update_leads_updated_at
            BEFORE UPDATE ON leads
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """
    )

    op.execute("DROP TRIGGER IF EXISTS update_deals_updated_at ON deals;")
    op.execute(
        """
        CREATE TRIGGER update_deals_updated_at
            BEFORE UPDATE ON deals
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """
    )

    op.execute("DROP TRIGGER IF EXISTS update_tasks_updated_at ON tasks;")
    op.execute(
        """
        CREATE TRIGGER update_tasks_updated_at
            BEFORE UPDATE ON tasks
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """
    )

    op.execute("DROP TRIGGER IF EXISTS update_notes_updated_at ON notes;")
    op.execute(
        """
        CREATE TRIGGER update_notes_updated_at
            BEFORE UPDATE ON notes
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """
    )

    if _is_supabase_connection(bind):
        op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE leads ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE deals ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE notes ENABLE ROW LEVEL SECURITY;")

        op.execute("DROP POLICY IF EXISTS \"authenticated_organizations_access\" ON organizations;")
        op.execute(
            """
            CREATE POLICY \"authenticated_organizations_access\"
                ON organizations FOR ALL TO authenticated
                USING (auth.role() = 'authenticated')
                WITH CHECK (auth.role() = 'authenticated');
            """
        )

        op.execute("DROP POLICY IF EXISTS \"authenticated_leads_access\" ON leads;")
        op.execute(
            """
            CREATE POLICY \"authenticated_leads_access\"
                ON leads FOR ALL TO authenticated
                USING (auth.role() = 'authenticated')
                WITH CHECK (auth.role() = 'authenticated');
            """
        )

        op.execute("DROP POLICY IF EXISTS \"authenticated_deals_access\" ON deals;")
        op.execute(
            """
            CREATE POLICY \"authenticated_deals_access\"
                ON deals FOR ALL TO authenticated
                USING (auth.role() = 'authenticated')
                WITH CHECK (auth.role() = 'authenticated');
            """
        )

        op.execute("DROP POLICY IF EXISTS \"authenticated_tasks_access\" ON tasks;")
        op.execute(
            """
            CREATE POLICY \"authenticated_tasks_access\"
                ON tasks FOR ALL TO authenticated
                USING (auth.role() = 'authenticated')
                WITH CHECK (auth.role() = 'authenticated');
            """
        )

        op.execute("DROP POLICY IF EXISTS \"authenticated_notes_access\" ON notes;")
        op.execute(
            """
            CREATE POLICY \"authenticated_notes_access\"
                ON notes FOR ALL TO authenticated
                USING (auth.role() = 'authenticated')
                WITH CHECK (auth.role() = 'authenticated');
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notes;")
    op.execute("DROP TABLE IF EXISTS tasks;")
    op.execute("DROP TABLE IF EXISTS deals;")
    op.execute("DROP TABLE IF EXISTS leads;")
    op.execute("DROP TABLE IF EXISTS organizations;")
