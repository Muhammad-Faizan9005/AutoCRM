"""add customer and organization record-level rls

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-06-26
"""

from alembic import op


revision = "t6u7v8w9x0y1"
down_revision = "s5t6u7v8w9x0"
branch_labels = None
depends_on = None


def _is_supabase_connection(bind) -> bool:
    host = (bind.engine.url.host or "").lower()
    return "supabase.co" in host


def upgrade() -> None:
    bind = op.get_bind()
    if not _is_supabase_connection(bind):
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION autocrm_can_access_owner_team(
            record_owner_id UUID,
            record_team_id UUID
        )
        RETURNS BOOLEAN
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            actor_id UUID := auth.uid();
            actor_role TEXT;
        BEGIN
            IF auth.role() = 'service_role' THEN
                RETURN TRUE;
            END IF;

            IF actor_id IS NULL THEN
                RETURN FALSE;
            END IF;

            SELECT lower(role) INTO actor_role
            FROM agents
            WHERE id = actor_id;

            IF actor_role = 'admin' THEN
                RETURN TRUE;
            END IF;

            IF record_owner_id = actor_id THEN
                RETURN TRUE;
            END IF;

            IF actor_role IN ('manager', 'sales_manager') THEN
                IF EXISTS (
                    SELECT 1
                    FROM team_members tm
                    JOIN teams t ON t.id = tm.team_id
                    WHERE t.manager_id = actor_id
                      AND tm.agent_id = record_owner_id
                ) THEN
                    RETURN TRUE;
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM teams t
                    WHERE t.manager_id = actor_id
                      AND t.id = record_team_id
                ) THEN
                    RETURN TRUE;
                END IF;
            END IF;

            RETURN FALSE;
        END;
        $$;
        """
    )

    op.execute("ALTER TABLE customers ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;")

    op.execute("DROP POLICY IF EXISTS authenticated_customers_access ON customers;")
    op.execute("DROP POLICY IF EXISTS \"authenticated_customers_access\" ON customers;")
    op.execute("DROP POLICY IF EXISTS customer_owner_team_access ON customers;")
    op.execute("DROP POLICY IF EXISTS service_role_customers_access ON customers;")

    op.execute("DROP POLICY IF EXISTS authenticated_organizations_access ON organizations;")
    op.execute("DROP POLICY IF EXISTS \"authenticated_organizations_access\" ON organizations;")
    op.execute("DROP POLICY IF EXISTS organization_owner_team_access ON organizations;")
    op.execute("DROP POLICY IF EXISTS service_role_organizations_access ON organizations;")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION autocrm_can_access_customer(
            customer_id UUID,
            record_owner_id UUID,
            record_team_id UUID
        )
        RETURNS BOOLEAN
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            actor_id UUID := auth.uid();
            actor_role TEXT;
        BEGIN
            IF autocrm_can_access_owner_team(record_owner_id, record_team_id) THEN
                RETURN TRUE;
            END IF;

            IF auth.role() = 'service_role' THEN
                RETURN TRUE;
            END IF;

            IF actor_id IS NULL THEN
                RETURN FALSE;
            END IF;

            SELECT lower(role) INTO actor_role
            FROM agents
            WHERE id = actor_id;

            IF actor_role = 'admin' THEN
                RETURN TRUE;
            END IF;

            IF actor_role IN ('manager', 'sales_manager') THEN
                RETURN EXISTS (
                    SELECT 1
                    FROM deals d
                    LEFT JOIN leads l ON l.id = d.lead_id
                    LEFT JOIN team_members deal_tm ON deal_tm.agent_id = d.owner_id
                    LEFT JOIN teams deal_team ON deal_team.id = deal_tm.team_id
                    LEFT JOIN team_members lead_tm ON lead_tm.agent_id = l.owner_id
                    LEFT JOIN teams lead_team ON lead_team.id = lead_tm.team_id
                    WHERE d.customer_id = customer_id
                      AND (
                        d.owner_id = actor_id
                        OR l.owner_id = actor_id
                        OR deal_team.manager_id = actor_id
                        OR lead_team.manager_id = actor_id
                      )
                );
            END IF;

            RETURN EXISTS (
                SELECT 1
                FROM deals d
                LEFT JOIN leads l ON l.id = d.lead_id
                WHERE d.customer_id = customer_id
                  AND (d.owner_id = actor_id OR l.owner_id = actor_id)
            );
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION autocrm_can_access_organization(
            organization_id UUID,
            record_owner_id UUID,
            record_team_id UUID
        )
        RETURNS BOOLEAN
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            actor_id UUID := auth.uid();
            actor_role TEXT;
        BEGIN
            IF autocrm_can_access_owner_team(record_owner_id, record_team_id) THEN
                RETURN TRUE;
            END IF;

            IF auth.role() = 'service_role' THEN
                RETURN TRUE;
            END IF;

            IF actor_id IS NULL THEN
                RETURN FALSE;
            END IF;

            SELECT lower(role) INTO actor_role
            FROM agents
            WHERE id = actor_id;

            IF actor_role = 'admin' THEN
                RETURN TRUE;
            END IF;

            IF actor_role IN ('manager', 'sales_manager') THEN
                RETURN EXISTS (
                    SELECT 1
                    FROM leads l
                    LEFT JOIN team_members tm ON tm.agent_id = l.owner_id
                    LEFT JOIN teams t ON t.id = tm.team_id
                    WHERE l.organization_id = organization_id
                      AND (l.owner_id = actor_id OR t.manager_id = actor_id)
                );
            END IF;

            RETURN EXISTS (
                SELECT 1
                FROM leads l
                WHERE l.organization_id = organization_id
                  AND l.owner_id = actor_id
            );
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE POLICY customer_owner_team_access
            ON customers FOR ALL TO authenticated
            USING (autocrm_can_access_customer(id, owner_id, team_id))
            WITH CHECK (autocrm_can_access_owner_team(owner_id, team_id));
        """
    )
    op.execute(
        """
        CREATE POLICY organization_owner_team_access
            ON organizations FOR ALL TO authenticated
            USING (autocrm_can_access_organization(id, owner_id, team_id))
            WITH CHECK (autocrm_can_access_owner_team(owner_id, team_id));
        """
    )
    op.execute(
        """
        CREATE POLICY service_role_customers_access
            ON customers FOR ALL TO service_role
            USING (true)
            WITH CHECK (true);
        """
    )
    op.execute(
        """
        CREATE POLICY service_role_organizations_access
            ON organizations FOR ALL TO service_role
            USING (true)
            WITH CHECK (true);
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_supabase_connection(bind):
        return

    op.execute("DROP POLICY IF EXISTS service_role_organizations_access ON organizations;")
    op.execute("DROP POLICY IF EXISTS service_role_customers_access ON customers;")
    op.execute("DROP POLICY IF EXISTS organization_owner_team_access ON organizations;")
    op.execute("DROP POLICY IF EXISTS customer_owner_team_access ON customers;")

    op.execute(
        """
        CREATE POLICY authenticated_customers_access
            ON customers FOR ALL TO authenticated
            USING (auth.role() = 'authenticated')
            WITH CHECK (auth.role() = 'authenticated');
        """
    )
    op.execute(
        """
        CREATE POLICY authenticated_organizations_access
            ON organizations FOR ALL TO authenticated
            USING (auth.role() = 'authenticated')
            WITH CHECK (auth.role() = 'authenticated');
        """
    )

    op.execute("DROP FUNCTION IF EXISTS autocrm_can_access_organization(UUID, UUID, UUID);")
    op.execute("DROP FUNCTION IF EXISTS autocrm_can_access_customer(UUID, UUID, UUID);")
    op.execute("DROP FUNCTION IF EXISTS autocrm_can_access_owner_team(UUID, UUID);")
