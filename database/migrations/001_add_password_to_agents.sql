-- Migration: Add password_hash column to agents table
-- Date: 2026-03-08
-- Description: Adds password authentication support to agents table

-- Add password_hash column if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'agents' 
        AND column_name = 'password_hash'
    ) THEN
        ALTER TABLE agents ADD COLUMN password_hash VARCHAR(255);
        
        -- Make it required for new records (optional: update existing records first)
        -- You may want to update existing records with a default password hash before running this
        ALTER TABLE agents ALTER COLUMN password_hash SET NOT NULL;
    END IF;
END $$;

-- Note: For existing agents, you need to set a password_hash before this migration
-- Example: UPDATE agents SET password_hash = '$2b$12$...' WHERE password_hash IS NULL;
