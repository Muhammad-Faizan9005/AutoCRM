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

        -- Existing rows receive a forced-reset placeholder before NOT NULL is enforced.
        UPDATE agents
        SET password_hash = '__PASSWORD_RESET_REQUIRED__'
        WHERE password_hash IS NULL;

        ALTER TABLE agents ALTER COLUMN password_hash SET NOT NULL;
    END IF;
END $$;
