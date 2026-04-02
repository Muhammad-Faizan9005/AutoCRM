-- Development seed data for local testing
-- Safe to run multiple times due ON CONFLICT clauses

INSERT INTO agents (id, email, password_hash, full_name, role, is_active)
VALUES
    ('11111111-1111-1111-1111-111111111111', 'admin@autocrm.local', '$2b$12$placeholder.hash.for.dev.only', 'AutoCRM Admin', 'admin', true),
    ('22222222-2222-2222-2222-222222222222', 'manager@autocrm.local', '$2b$12$placeholder.hash.for.dev.only', 'Sales Manager', 'sales_manager', true),
    ('33333333-3333-3333-3333-333333333333', 'rep@autocrm.local', '$2b$12$placeholder.hash.for.dev.only', 'Sales Rep', 'sales_rep', true)
ON CONFLICT (email) DO NOTHING;

INSERT INTO customers (id, email, full_name, phone, company, status, notes)
VALUES
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'customer.one@example.com', 'Customer One', '+1 555 0101', 'Acme Inc', 'active', 'Priority customer'),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'customer.two@example.com', 'Customer Two', '+1 555 0102', 'Globex Corp', 'lead', 'New inbound lead')
ON CONFLICT (email) DO NOTHING;

INSERT INTO tickets (id, customer_id, subject, description, status, priority, category)
VALUES
    ('cccccccc-cccc-cccc-cccc-cccccccccccc', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Onboarding issue', 'Customer needs account onboarding help', 'open', 'high', 'onboarding'),
    ('dddddddd-dddd-dddd-dddd-dddddddddddd', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'Product question', 'Interested in enterprise plan details', 'pending', 'medium', 'sales')
ON CONFLICT (id) DO NOTHING;

INSERT INTO ticket_messages (id, ticket_id, sender_type, content)
VALUES
    ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'cccccccc-cccc-cccc-cccc-cccccccccccc', 'customer', 'I need help setting up my account.'),
    ('ffffffff-ffff-ffff-ffff-ffffffffffff', 'cccccccc-cccc-cccc-cccc-cccccccccccc', 'agent', 'Sure, I can help you with that right now.')
ON CONFLICT (id) DO NOTHING;
