-- Migration: update agent roles for Day 2 RBAC model
-- Date: 2026-03-19
-- Roles become: admin, sales_manager, sales_rep

BEGIN;

-- Map previous role names into new role model.
UPDATE agents SET role = 'sales_manager' WHERE role = 'supervisor';
UPDATE agents SET role = 'sales_rep' WHERE role = 'agent';

-- Replace old check constraint with the new RBAC role values.
ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_role_check;
ALTER TABLE agents ADD CONSTRAINT agents_role_check
CHECK (role IN ('admin', 'sales_manager', 'sales_rep'));

-- Ensure default aligns with new base role.
ALTER TABLE agents ALTER COLUMN role SET DEFAULT 'sales_rep';

COMMIT;
