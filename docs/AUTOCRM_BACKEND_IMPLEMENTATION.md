# AutoCRM Backend Implementation (Detailed)

Last updated: 2026-05-30

This document describes the current backend implementation. For each feature you will see:
- Why: the business or operational reason the capability exists.
- How: the runtime flow and important constraints.
- Where: the exact source files that implement the behavior.

## 1) System overview

AutoCRM backend is a FastAPI service that exposes a REST API for CRM operations, admin governance, and team workflows. It is built around a repository + service architecture, uses PostgreSQL via Supabase client + SQLAlchemy connection for complex queries, and uses Alembic for schema migrations and versioning.

Why
- Provide a stable, production-ready CRM API with strong permissions and admin oversight.
- Keep business logic centralized in services while repositories handle persistence.

How
- FastAPI app wiring and middleware are configured in a single entry point.
- Routers expose domain endpoints and depend on auth + permission guards.
- Repositories encapsulate CRUD operations for each entity.
- Services implement cross-entity flows (conversion, imports, notifications, email, dashboard summary).

Where
- App setup: [backend/app/main.py](backend/app/main.py)
- Routers: [backend/app/routers](backend/app/routers)
- Repositories: [backend/app/repositories](backend/app/repositories)
- Services: [backend/app/services](backend/app/services)
- Schemas: [backend/app/schemas](backend/app/schemas)

## 2) Request lifecycle and cross-cutting concerns

Why
- Ensure consistent security headers, error responses, and rate limiting across all endpoints.

How
- Middleware order is critical: security -> rate limit -> logging -> error handling.
- CORS is configured for known frontend origins.
- Request IDs and structured error responses are attached by middleware.
- Static assets are served from the storage directory.

Where
- Middleware registration and CORS: [backend/app/main.py](backend/app/main.py)
- Error handler middleware: [backend/app/middleware/error_handler.py](backend/app/middleware/error_handler.py)
- Logging middleware: [backend/app/middleware/logging_middleware.py](backend/app/middleware/logging_middleware.py)
- Rate limiting: [backend/app/middleware/rate_limiter.py](backend/app/middleware/rate_limiter.py)
- Security headers: [backend/app/middleware/security.py](backend/app/middleware/security.py)

## 3) Authentication and session model

Why
- Provide secure, stateless authentication with revocation support and refresh rotation.

How
- JWT access and refresh tokens are issued on register and login.
- Refresh tokens are rotated and blacklisted after use.
- Access tokens are verified on each request, with blacklist checks.
- User data is cached for 5 minutes to reduce DB reads.
- Account inactivity blocks access even if the token is valid.

Where
- Auth endpoints: [backend/app/routers/auth.py](backend/app/routers/auth.py)
- Auth helpers (hashing, tokens): [backend/app/auth/utils.py](backend/app/auth/utils.py)
- Auth dependencies and guards: [backend/app/auth/dependencies.py](backend/app/auth/dependencies.py)
- Token blacklist: [backend/app/auth/token_store.py](backend/app/auth/token_store.py)
- Cache utilities: [backend/app/utils/cache.py](backend/app/utils/cache.py)

## 4) Role and permission system

Why
- Allow granular feature access (CRM modules, imports, admin tools) beyond simple roles.

How
- Permissions are derived from role defaults and optional overrides.
- Overrides are stored in an agent permissions record and also mirrored into JSON files for auditability.
- Admin users always receive all admin and import permissions.

Where
- Permission resolution and storage: [backend/app/services/permission_service.py](backend/app/services/permission_service.py)
- Permission-protected routes: [backend/app/auth/dependencies.py](backend/app/auth/dependencies.py)

## 5) Admin console and governance

### 5.1 Admin overview

Why
- Give admins a governance dashboard for user access, imports, and coverage.

How
- Aggregates counts for active users, permission updates, import activity, and module coverage.
- Returns a structured overview for the admin dashboard UI.

Where
- Overview service: [backend/app/services/admin_overview_service.py](backend/app/services/admin_overview_service.py)
- Overview endpoint: [backend/app/routers/admin.py](backend/app/routers/admin.py)

### 5.2 User management

Why
- Provide the full lifecycle for CRM operators: create, invite, enable/disable, delete, and audit.

How
- Admins can create any role; managers can create only sales reps.
- Sales reps must be assigned to teams at creation time.
- Invited users are created with status=invited and can accept via invite link.
- Deleted users are archived into deleted_users with assignment cleanup and metadata.

Where
- Admin user endpoints: [backend/app/routers/admin.py](backend/app/routers/admin.py)
- Registration helper: [backend/app/services/registration_service.py](backend/app/services/registration_service.py)
- Deleted user archival: [backend/app/routers/admin.py](backend/app/routers/admin.py)

### 5.3 Invites and failed invites

Why
- Control onboarding with email invites, and provide a recovery path if invites fail or expire.

How
- Invites are created with hashed tokens and TTL; acceptance activates the user.
- Expired or revoked invites are recorded in failed_invites and can be re-sent.

Where
- Invite endpoints: [backend/app/routers/invites.py](backend/app/routers/invites.py)
- Invite management: [backend/app/services/invite_service.py](backend/app/services/invite_service.py)
- Admin failed invite endpoints: [backend/app/routers/admin.py](backend/app/routers/admin.py)

### 5.4 Permission management

Why
- Allow per-user feature access control for CRM and admin modules.

How
- Admins and managers can retrieve and update permissions.
- Permissions are sanitized, merged with role defaults, and persisted.

Where
- Permission endpoints: [backend/app/routers/admin.py](backend/app/routers/admin.py)
- Permission logic: [backend/app/services/permission_service.py](backend/app/services/permission_service.py)

## 6) Teams and team access

Why
- Support manager ownership of sales reps and scoped access to their records.

How
- Managers can create one team and manage its members.
- Admins can list all teams, edit managers, and view member stats.
- Access control uses team membership to restrict lead/deal/task visibility.

Where
- Team endpoints: [backend/app/routers/teams.py](backend/app/routers/teams.py)
- Team access rules: [backend/app/utils/team_access.py](backend/app/utils/team_access.py)

## 7) CRM Core modules

### 7.1 Leads

Why
- Capture prospects, assign ownership, and convert to deals.

How
- Managers see leads for their team; reps see their own; admins see all.
- Lead assignment is restricted by role and team membership.
- Status changes are normalized and logged to status_change_logs.
- Notifications + email are sent when a lead is assigned.
- Lead conversion creates a deal and marks the lead as qualified.
- Lead email timeline endpoint currently returns mock data.

Where
- Lead endpoints: [backend/app/routers/leads.py](backend/app/routers/leads.py)
- Lead access checks: [backend/app/utils/team_access.py](backend/app/utils/team_access.py)
- Status logging: [backend/app/services/status_change_log_service.py](backend/app/services/status_change_log_service.py)
- Conversion flow: [backend/app/services/conversion_service.py](backend/app/services/conversion_service.py)
- Assignment notifications: [backend/app/services/notification_service.py](backend/app/services/notification_service.py)
- Assignment emails: [backend/app/services/email_service.py](backend/app/services/email_service.py)

### 7.2 Deals

Why
- Track revenue opportunities and close them into customers.

How
- Managers see team deals; reps see own; admins see all.
- Deal status updates are normalized and logged.
- When status becomes won, a customer is created and the deal is closed.

Where
- Deal endpoints: [backend/app/routers/deals.py](backend/app/routers/deals.py)
- Conversion flow: [backend/app/services/conversion_service.py](backend/app/services/conversion_service.py)
- Status logging: [backend/app/services/status_change_log_service.py](backend/app/services/status_change_log_service.py)

### 7.3 Customers (Contacts)

Why
- Track active customers and their contact details.

How
- Basic CRUD with optional status filter.
- Admin-only delete.

Where
- Customer endpoints: [backend/app/routers/customers.py](backend/app/routers/customers.py)
- Customer repository: [backend/app/repositories/customer_repository.py](backend/app/repositories/customer_repository.py)

### 7.4 Organizations

Why
- Group contacts and deals under company-level profiles.

How
- CRUD with optional industry and search filters.
- Admin-only delete.

Where
- Organization endpoints: [backend/app/routers/organizations.py](backend/app/routers/organizations.py)
- Organization repository: [backend/app/repositories/organization_repository.py](backend/app/repositories/organization_repository.py)

### 7.5 Tasks

Why
- Drive sales workflows with assignments and due dates.

How
- Admins and managers can create and assign tasks; reps can only update status.
- Tasks can be linked to leads (entity_type=lead) with access checks.
- Assignment changes trigger notifications and email.

Where
- Task endpoints: [backend/app/routers/tasks.py](backend/app/routers/tasks.py)
- Notification/email helpers: [backend/app/services/notification_service.py](backend/app/services/notification_service.py), [backend/app/services/email_service.py](backend/app/services/email_service.py)

### 7.6 Notes

Why
- Record internal commentary and lead-specific context.

How
- Notes can be linked to any entity type; lead notes are access-scoped.
- Lead note creation triggers a notification to the lead owner.
- Only admins or the original author can edit/delete a note.

Where
- Notes endpoints: [backend/app/routers/notes.py](backend/app/routers/notes.py)
- Notification helper: [backend/app/services/notification_service.py](backend/app/services/notification_service.py)

### 7.7 Tickets and messages

Why
- Support customer support requests and threaded ticket communication.

How
- CRUD for tickets with optional status and priority filters.
- Ticket assignment restricted to admin or sales_manager.
- Ticket messages are stored per ticket and can be listed or created.

Where
- Ticket endpoints: [backend/app/routers/tickets.py](backend/app/routers/tickets.py)
- Ticket repository: [backend/app/repositories/ticket_repository.py](backend/app/repositories/ticket_repository.py)

## 8) Notifications

Why
- Provide in-app alerts for assignments and actions.

How
- Notifications are created by services and stored per recipient.
- Recipients can mark notifications read or mark all read.

Where
- Notification endpoints: [backend/app/routers/notifications.py](backend/app/routers/notifications.py)
- Notification service: [backend/app/services/notification_service.py](backend/app/services/notification_service.py)
- Notification repository: [backend/app/repositories/notification_repository.py](backend/app/repositories/notification_repository.py)

## 9) Email delivery and preferences

Why
- Send operational email for invites, password reset, lead/task assignment, and calls.

How
- Mailjet provider is used; missing credentials return service unavailable.
- Email preferences per user/role control which events send email.
- All outbound mail attempts are logged in email_logs.

Where
- Email service: [backend/app/services/email_service.py](backend/app/services/email_service.py)
- Invite flow integration: [backend/app/services/invite_service.py](backend/app/services/invite_service.py)
- Password reset email: [backend/app/routers/auth.py](backend/app/routers/auth.py)

## 10) Data imports

Why
- Allow bulk ingest of CRM data from CSV/XLSX.

How
- CSV and Excel files are parsed with header normalization.
- Lead imports upsert by email and can auto-create organizations.
- Ticket imports accept customer_id or customer_email.
- Import results include row counts and failure reasons.

Where
- Import endpoints: [backend/app/routers/imports.py](backend/app/routers/imports.py)
- Import service: [backend/app/services/import_service.py](backend/app/services/import_service.py)

## 11) Dashboard metrics

Why
- Provide KPI summaries and activity trends for the CRM home dashboard.

How
- Summary aggregates totals for leads, deals, orgs, tasks, notes, revenue, and pipeline.
- Activity endpoint groups daily counts for leads, deals, tasks, notes.
- Responses are cached for 60 seconds to limit database load.

Where
- Dashboard endpoints: [backend/app/routers/dashboard.py](backend/app/routers/dashboard.py)
- Dashboard service: [backend/app/services/dashboard_service.py](backend/app/services/dashboard_service.py)

## 12) Calls and recordings

Why
- Enable lead call sessions with a browser-based audio experience.

How
- Call sessions are created for a lead and email invite links are generated.
- Secure room tokens are stored and validated for call join.
- WebSocket signaling coordinates WebRTC offer/answer/ICE messages.
- Recordings are uploaded and stored on disk under the call recordings directory.

Where
- Call endpoints + WebSocket signaling: [backend/app/routers/calls.py](backend/app/routers/calls.py)
- Call repository: [backend/app/repositories/call_repository.py](backend/app/repositories/call_repository.py)
- Call invite email: [backend/app/services/email_service.py](backend/app/services/email_service.py)

## 13) Known placeholders and current limits

Why
- Document current implementation boundaries to avoid confusion.

How
- Lead email timeline endpoint returns mocked email data.
- AI/LLM endpoints are not implemented in this backend version.

Where
- Lead email timeline: [backend/app/routers/leads.py](backend/app/routers/leads.py)
- API scope overview: [backend/docs/API.md](backend/docs/API.md)

