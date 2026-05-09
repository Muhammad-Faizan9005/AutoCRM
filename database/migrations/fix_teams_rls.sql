-- =============================================
-- RLS FIX for teams and team_members tables
-- Run this in Supabase SQL Editor
-- =============================================

-- 1. Enable RLS on both tables
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_members ENABLE ROW LEVEL SECURITY;

-- 2. Allow authenticated users full access (backend handles authorization)
CREATE POLICY "authenticated_teams_access"
    ON teams FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "authenticated_team_members_access"
    ON team_members FOR ALL TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

-- 3. Also allow service_role full access (for backend operations)
CREATE POLICY "service_role_teams_access"
    ON teams FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_team_members_access"
    ON team_members FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- 4. Allow anon role full access (if your pooler connects as anon)
CREATE POLICY "anon_teams_access"
    ON teams FOR ALL TO anon
    USING (true)
    WITH CHECK (true);

CREATE POLICY "anon_team_members_access"
    ON team_members FOR ALL TO anon
    USING (true)
    WITH CHECK (true);
