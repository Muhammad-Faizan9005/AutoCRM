-- Composite indexes for workspace endpoints and common CRM list filters.

CREATE INDEX IF NOT EXISTS idx_tasks_entity_type_entity_id_due_at
ON tasks(entity_type, entity_id, due_at);

CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to_status_due_at
ON tasks(assigned_to, status, due_at);

CREATE INDEX IF NOT EXISTS idx_notes_entity_type_entity_id_created_at
ON notes(entity_type, entity_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_call_sessions_lead_id_started_at
ON call_sessions(lead_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_deals_owner_id_created_at
ON deals(owner_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_deals_lead_id_created_at
ON deals(lead_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient_id_created_at
ON notifications(recipient_id, created_at DESC);
