# AutoCRM Backend Implementation (Detailed)

Last updated: 2026-07-28

This document describes the current backend implementation. For each feature you will see:
- Why: the business or operational reason the capability exists.
- How: the runtime flow and important constraints.
- Where: the exact source files that implement the behavior.

Paths are relative to this file (`backend/docs/`).

## 1) System overview

AutoCRM backend is a FastAPI service that exposes a REST API for CRM operations, admin governance, team workflows, and the AI control plane. It is built around a repository + service architecture, uses PostgreSQL via Supabase client + SQLAlchemy connection for complex queries, and uses Alembic for schema migrations and versioning.

Why
- Provide a stable, production-ready CRM API with strong permissions and admin oversight.
- Keep business logic centralized in services while repositories handle persistence.
- Own all AI-proposed writes so an autonomous agent can never bypass approval or RBAC.

How
- FastAPI app wiring and middleware are configured in a single entry point.
- Routers expose domain endpoints and depend on auth + permission guards.
- Repositories encapsulate CRUD operations for each entity.
- Services implement cross-entity flows (conversion, imports, notifications, email, dashboard summary, task deadlines, lead scoring).

Where
- App setup: [../app/main.py](../app/main.py)
- Routers: [../app/routers](../app/routers)
- Repositories: [../app/repositories](../app/repositories)
- Services: [../app/services](../app/services)
- Schemas: [../app/schemas](../app/schemas)

## 2) Request lifecycle and cross-cutting concerns

Why
- Ensure consistent security headers, error responses, and rate limiting across all endpoints.

How
- Middleware is registered so the **last registered runs first**. Effective order per request is: error handler -> logging -> rate limit -> security -> CSRF.
- CORS is registered before the custom middleware so preflight requests get CORS headers, and is allow-listed to known frontend origins (`allow_credentials=True` forbids a wildcard).
- Request IDs and structured error responses are attached by middleware.
- Avatars are served from a `/static/avatars` static mount.
- Startup runs `verify_startup_config()`, which aborts in production (`DEBUG=False`) and warns in development, then warms table metadata in a background task so health checks are not blocked.

Where
- Middleware registration and CORS: [../app/main.py](../app/main.py)
- Startup validation: [../app/core/startup_checks.py](../app/core/startup_checks.py)
- Error handler middleware: [../app/middleware/error_handler.py](../app/middleware/error_handler.py)
- Logging middleware: [../app/middleware/logging_middleware.py](../app/middleware/logging_middleware.py)
- Rate limiting: [../app/middleware/rate_limiter.py](../app/middleware/rate_limiter.py)
- Security headers: [../app/middleware/security.py](../app/middleware/security.py)
- CSRF middleware: [../app/auth/cookies.py](../app/auth/cookies.py)

## 3) Authentication and session model

Why
- Provide secure authentication with revocation support and refresh rotation, without exposing tokens to JavaScript.

How
- JWT access and refresh tokens are issued on register and login and delivered **only as HttpOnly cookies**. No endpoint returns a token in its response body.
- `get_current_user` reads the `access_token` cookie; there is no `Authorization: Bearer` fallback for user auth.
- A readable `csrf_token` cookie backs a double-submit check on all mutating requests; login and register are exempt.
- The `refresh_token` cookie is scoped to `/api/auth`. Refresh takes no body, rotates the pair, and blacklists the old refresh token.
- Access tokens are verified on each request, with blacklist checks against `revoked_tokens`.
- User data is cached for 5 minutes to reduce DB reads.
- Account inactivity blocks access even if the token is valid.

Where
- Auth endpoints: [../app/routers/auth.py](../app/routers/auth.py)
- Cookie + CSRF handling: [../app/auth/cookies.py](../app/auth/cookies.py)
- Auth helpers (hashing, tokens): [../app/auth/utils.py](../app/auth/utils.py)
- Auth dependencies and guards: [../app/auth/dependencies.py](../app/auth/dependencies.py)
- Token blacklist: [../app/auth/token_store.py](../app/auth/token_store.py)
- Cache utilities: [../app/utils/cache.py](../app/utils/cache.py)

## 4) Role and permission system

Why
- Allow granular feature access (CRM modules, imports, admin tools) beyond simple roles.

How
- Permissions are derived from role defaults and optional overrides.
- Overrides are stored in an agent permissions record and also mirrored into JSON files under `storage/permissions/` for auditability.
- Admin users always receive all admin and import permissions.
- Beyond route guards, list endpoints scope rows by role: reps see what they own, managers see their team via `team_members`, admins see everything.

Where
- Permission resolution and storage: [../app/services/permission_service.py](../app/services/permission_service.py)
- Permission-protected routes: [../app/auth/dependencies.py](../app/auth/dependencies.py)
- Team-based row scoping: [../app/utils/team_access.py](../app/utils/team_access.py)

## 5) Admin console and governance

### 5.1 Admin overview

Why
- Give admins a governance dashboard for user access, imports, and coverage.

How
- Aggregates counts for active users, permission updates, import activity, and module coverage.
- Returns a structured overview for the admin dashboard UI.

Where
- Overview service: [../app/services/admin_overview_service.py](../app/services/admin_overview_service.py)
- Overview endpoint: [../app/routers/admin.py](../app/routers/admin.py)

### 5.2 User management

Why
- Provide the full lifecycle for CRM operators: create, invite, enable/disable, delete, and audit.

How
- Admins can create any role; managers can create only sales reps.
- Sales reps must be assigned to teams at creation time.
- Invited users are created with status=invited and can accept via invite link.
- Deleted users are archived into deleted_users with assignment cleanup and metadata.

Where
- Admin user endpoints: [../app/routers/admin.py](../app/routers/admin.py)
- Registration helper: [../app/services/registration_service.py](../app/services/registration_service.py)
- Activity log: [../app/services/admin_activity_log_service.py](../app/services/admin_activity_log_service.py)

### 5.3 Invites and failed invites

Why
- Control onboarding with email invites, and provide a recovery path if invites fail or expire.

How
- Invites are created with hashed tokens and TTL (`INVITE_TOKEN_TTL_HOURS`, default 72); acceptance activates the user.
- Expired or revoked invites are recorded in failed_invites and can be re-sent.

Where
- Invite endpoints: [../app/routers/invites.py](../app/routers/invites.py)
- Invite management: [../app/services/invite_service.py](../app/services/invite_service.py)
- Admin failed invite endpoints: [../app/routers/admin.py](../app/routers/admin.py)

### 5.4 Permission management

Why
- Allow per-user feature access control for CRM and admin modules.

How
- Admins and managers can retrieve and update permissions.
- Permissions are sanitized, merged with role defaults, and persisted.

Where
- Permission endpoints: [../app/routers/admin.py](../app/routers/admin.py)
- Permission logic: [../app/services/permission_service.py](../app/services/permission_service.py)

## 6) Teams and team access

Why
- Support manager ownership of sales reps and scoped access to their records.

How
- Managers can create one team and manage its members.
- Admins can list all teams, edit managers, and view member stats.
- Access control uses team membership to restrict lead/deal/task visibility.
- A unique constraint prevents an agent appearing twice in the same team.
- Team routes are mounted at `/api/admin/teams` **without** a trailing slash.

Where
- Team endpoints: [../app/routers/teams.py](../app/routers/teams.py)
- Team access rules: [../app/utils/team_access.py](../app/utils/team_access.py)

## 7) CRM Core modules

### 7.1 Leads

Why
- Capture prospects, assign ownership, and convert to deals.

How
- Managers see leads for their team; reps see their own; admins see all.
- Lead assignment is restricted by role and team membership.
- Status changes are normalized against a canonical taxonomy and logged to status_change_logs.
- Notifications + email are sent when a lead is assigned.
- Lead conversion creates a deal and marks the lead as qualified.
- A `workspace` endpoint returns the lead plus its tasks, notes, and activity in one round trip so the detail page avoids a request waterfall.
- Lead scores are recalculated on demand and by a scheduled sweep.
- Lead email timeline endpoint currently returns mock data.

Where
- Lead endpoints: [../app/routers/leads.py](../app/routers/leads.py)
- Lead access checks: [../app/utils/team_access.py](../app/utils/team_access.py)
- Status normalization: [../app/utils/statuses.py](../app/utils/statuses.py)
- Status logging: [../app/services/status_change_log_service.py](../app/services/status_change_log_service.py)
- Conversion flow: [../app/services/conversion_service.py](../app/services/conversion_service.py)
- Lead scoring: [../app/services/lead_scoring_service.py](../app/services/lead_scoring_service.py)
- Assignment notifications: [../app/services/notification_service.py](../app/services/notification_service.py)
- Assignment emails: [../app/services/email_service.py](../app/services/email_service.py)

### 7.2 Deals

Why
- Track revenue opportunities and close them into customers.

How
- Managers see team deals; reps see own; admins see all.
- Deal status updates are normalized and logged.
- When status becomes won, a customer is created and the deal is closed.
- `lost_reason` is captured on lost deals so pipeline analytics stay meaningful.

Where
- Deal endpoints: [../app/routers/deals.py](../app/routers/deals.py)
- Conversion flow: [../app/services/conversion_service.py](../app/services/conversion_service.py)
- Status logging: [../app/services/status_change_log_service.py](../app/services/status_change_log_service.py)

### 7.3 Customers (Contacts)

Why
- Track active customers and their contact details.

How
- Basic CRUD with optional status filter.
- Ownership columns and RLS restrict cross-tenant visibility.
- Admin-only delete.

Where
- Customer endpoints: [../app/routers/customers.py](../app/routers/customers.py)
- Customer repository: [../app/repositories/customer_repository.py](../app/repositories/customer_repository.py)

### 7.4 Organizations

Why
- Group contacts and deals under company-level profiles.

How
- CRUD with optional industry and search filters.
- A `workspace` endpoint returns the org with its related leads and deals.
- Admin-only delete.

Where
- Organization endpoints: [../app/routers/organizations.py](../app/routers/organizations.py)
- Organization repository: [../app/repositories/organization_repository.py](../app/repositories/organization_repository.py)

### 7.5 Tasks

Why
- Drive sales workflows with assignments and due dates.

How
- Admins and managers can create and assign tasks; reps can only update status.
- Tasks can be linked to leads (entity_type=lead) with access checks.
- Assignment changes trigger notifications and email.
- A deadline watcher flags tasks approaching or past their due date and records alerts.

Where
- Task endpoints: [../app/routers/tasks.py](../app/routers/tasks.py)
- Deadline monitoring: [../app/services/task_deadline_service.py](../app/services/task_deadline_service.py)
- Notification/email helpers: [../app/services/notification_service.py](../app/services/notification_service.py), [../app/services/email_service.py](../app/services/email_service.py)

### 7.6 Notes

Why
- Record internal commentary and lead-specific context.

How
- Notes can be linked to any entity type; lead notes are access-scoped.
- Lead note creation triggers a notification to the lead owner.
- Only admins or the original author can edit/delete a note.

Where
- Notes endpoints: [../app/routers/notes.py](../app/routers/notes.py)
- Notification helper: [../app/services/notification_service.py](../app/services/notification_service.py)

### 7.7 Tickets and messages

Why
- Support customer support requests and threaded ticket communication.

How
- CRUD for tickets with optional status and priority filters.
- Ticket assignment restricted to admin or sales_manager.
- Ticket messages are stored per ticket and can be listed or created.

Where
- Ticket endpoints: [../app/routers/tickets.py](../app/routers/tickets.py)
- Ticket repository: [../app/repositories/ticket_repository.py](../app/repositories/ticket_repository.py)

## 8) Notifications

Why
- Provide in-app alerts for assignments and actions.

How
- Notifications are created by services and stored per recipient.
- Recipients can mark notifications read or mark all read.
- Severity and label handling distinguishes routine assignments from AI approval requests and deadline alerts.

Where
- Notification endpoints: [../app/routers/notifications.py](../app/routers/notifications.py)
- Notification service: [../app/services/notification_service.py](../app/services/notification_service.py)
- Notification repository: [../app/repositories/notification_repository.py](../app/repositories/notification_repository.py)

## 9) Email delivery and preferences

Why
- Send operational email for invites, password reset, lead/task assignment, and calls.

How
- Mailjet provider is used; missing credentials return service unavailable.
- Email preferences per user/role control which events send email.
- All outbound mail attempts are logged in email_logs.

Where
- Email service: [../app/services/email_service.py](../app/services/email_service.py)
- Invite flow integration: [../app/services/invite_service.py](../app/services/invite_service.py)
- Password reset email: [../app/routers/auth.py](../app/routers/auth.py)

## 10) Data imports

Why
- Allow bulk ingest of CRM data from CSV/XLSX.

How
- CSV and Excel files are parsed with header normalization.
- Lead imports upsert by email and can auto-create organizations.
- Ticket imports accept customer_id or customer_email.
- Import results include row counts and failure reasons.
- Bounded by `IMPORT_MAX_FILE_BYTES` (default 5 MB) and `IMPORT_MAX_ROWS` (default 5000).

Where
- Import endpoints: [../app/routers/imports.py](../app/routers/imports.py)
- Import service: [../app/services/import_service.py](../app/services/import_service.py)

## 11) Dashboard metrics

Why
- Provide KPI summaries and activity trends for the CRM home dashboard.

How
- Summary aggregates totals for leads, deals, orgs, tasks, notes, revenue, and pipeline.
- Metrics are role-scoped, so a manager's dashboard reflects their team rather than the whole tenant.
- Activity endpoint groups daily counts for leads, deals, tasks, notes.
- Responses are cached for 60 seconds, keyed by scope, to limit database load.

Where
- Dashboard endpoints: [../app/routers/dashboard.py](../app/routers/dashboard.py)
- Dashboard service: [../app/services/dashboard_service.py](../app/services/dashboard_service.py)

## 12) Calls and recordings

Why
- Enable lead call sessions with a browser-based audio experience.

How
- Call sessions are created for a lead and email invite links are generated.
- Secure room tokens are stored and validated for call join (`CALL_ROOM_TOKEN_TTL_MINUTES`, default 15).
- WebSocket signaling coordinates WebRTC offer/answer/ICE messages.
- Recordings upload in chunks and are stored on disk under the call recordings directory, bounded by `CALL_RECORDING_CHUNK_MAX_BYTES` and `CALL_RECORDING_MAX_BYTES`.
- On completion the backend notifies the AI service so transcription can start.

Where
- Call endpoints + WebSocket signaling: [../app/routers/calls.py](../app/routers/calls.py)
- Call repository: [../app/repositories/call_repository.py](../app/repositories/call_repository.py)
- AI transcription handoff: [../app/services/ai_transcription_client.py](../app/services/ai_transcription_client.py)
- Call invite email: [../app/services/email_service.py](../app/services/email_service.py)

## 13) AI control plane

Why
- The AI service runs autonomously, so the backend must remain the single point where AI-proposed changes are authorized, audited, and applied. Letting the agent write CRM rows directly would bypass RBAC and leave no audit trail.

How
- The AI service authenticates with `X-AI-Service-Token` (SHA-256 hashed against `ai_agent_credentials`), optionally tagging runtime attribution with `X-AI-Agent-Key`. Credentials must be active and unexpired.
- Credentials are issued from Profile Settings -> Developer Mode; the raw token is shown once and only its hash is stored.
- The AI service creates runs with stable external IDs, appends trace steps, and dispatches proposed actions to `/api/agent/actions`.
- Actions that require review become approval requests; an admin approves or rejects, and only on approval does the backend perform the CRM write.
- The backend also exposes read-only workflow feeds (stale leads, at-risk deals, summary candidates, task deadline candidates, entity snapshots, RAG document snapshots) so the AI service never queries CRM tables directly.
- An `ai_agents` registry tracks each logical agent's enabled state, status, and last heartbeat, surfaced in the AI Control Center UI.

Where
- Control plane endpoints: [../app/routers/agent.py](../app/routers/agent.py)
- Service auth: [../app/auth/dependencies.py](../app/auth/dependencies.py)
- Control plane persistence: [../app/repositories/agent_control_repository.py](../app/repositories/agent_control_repository.py)
- Action schemas: [../app/schemas/agent_action.py](../app/schemas/agent_action.py)

## 14) Reliability utilities

Why
- Outbound dependencies (Mailjet, Supabase storage, the AI service) fail independently of this backend, and a slow dependency should not exhaust the request pool.

How
- A retry helper with backoff wraps transient outbound failures.
- A circuit breaker trips after repeated failures so a dead dependency fails fast instead of blocking.
- DB concurrency is capped by `DB_MAX_CONCURRENT_OPERATIONS`, kept at or below pool size + overflow to avoid waiter pileups.
- Avatar storage falls back to local disk; `AVATARS_ENABLED=false` skips S3 entirely on networks that block the storage host.

Where
- Retry: [../app/utils/retry.py](../app/utils/retry.py)
- Circuit breaker: [../app/utils/circuit_breaker.py](../app/utils/circuit_breaker.py)
- DB session/pool: [../app/database.py](../app/database.py), [../app/db/session.py](../app/db/session.py)
- Avatar storage: [../app/services/avatar_storage.py](../app/services/avatar_storage.py)

## 15) Known placeholders and current limits

Why
- Document current implementation boundaries to avoid confusion.

How
- Lead email timeline endpoint returns mocked email data — there is no email-sync integration.
- Rate limiting and the user cache are in-process, so limits and cache hits are per worker rather than global. A shared store would be needed for multi-instance deployments.
- Permission overrides are mirrored to JSON files on local disk, which does not survive an ephemeral filesystem.
- LLM inference itself lives in the separate AI service; this backend holds the control plane and never calls a model provider directly.

Where
- Lead email timeline: [../app/routers/leads.py](../app/routers/leads.py)
- Rate limiter: [../app/middleware/rate_limiter.py](../app/middleware/rate_limiter.py)
- Permission file mirror: [../app/services/permission_service.py](../app/services/permission_service.py)
- API scope overview: [API.md](API.md)

