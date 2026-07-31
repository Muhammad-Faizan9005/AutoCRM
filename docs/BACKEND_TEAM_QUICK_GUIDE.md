# AutoCRM Backend Quick Guide

Last Updated: 2026-07-28

An orientation document for people new to this backend. For exact endpoint
contracts use [API.md](API.md).

## 1) What This Backend Does

- Provides CRM APIs for auth, users, leads, deals, organizations, customers,
  tasks, notes, tickets, notifications, calls, imports, teams, and the admin console.
- Hosts the **AI control plane** (`/api/agent`): the backend is the source of
  truth for AI runs, traces, proposed actions, and approvals. The separate AI
  service calls into these endpoints rather than writing CRM data directly.
- Uses PostgreSQL (Supabase-hosted) through a custom query client.
- Uses JWT authentication delivered as HttpOnly cookies, with refresh rotation.
- Applies role-based access control (`admin`, `sales_manager`, `sales_rep`)
  plus per-user permission overrides.
- Adds production-focused middleware (CSRF, security headers, request size
  guard, rate limiting, request ID, logging, error format).

## 2) Fundamentals (simple definitions)

### FastAPI

- A Python web framework for building APIs quickly.
- Gives routing, dependency injection, request validation, and OpenAPI docs out of the box.
- In this project, FastAPI app startup is in `app/main.py`.

### REST API

- A style of API where resources are exposed via URLs and HTTP methods.
- Example in this backend:
  - `GET /api/leads/` -> list leads
  - `POST /api/tickets/` -> create ticket

### JWT (JSON Web Token)

- A signed token used for stateless authentication.
- Backend verifies signature and claims on every protected request.
- This project uses:
  - Access token (short-lived, default 30 minutes)
  - Refresh token (longer-lived, default 7 days)

### Access Token vs Refresh Token

- Access token: sent automatically as the HttpOnly `access_token` cookie.
- Refresh token: the `refresh_token` cookie, scoped to `/api/auth`, used only to
  mint a new pair when the access token expires.
- This backend rotates refresh tokens and revokes old ones in `revoked_tokens`.
- There is **no** `Authorization: Bearer` path for user auth — `get_current_user`
  reads the cookie only.

### CSRF (double-submit)

- Because auth rides on cookies, mutating requests need proof they came from our
  frontend and not another site.
- The backend also sets a readable `csrf_token` cookie. The client copies its
  value into an `X-CSRF-Token` header on every `POST`/`PUT`/`PATCH`/`DELETE`.
- `csrf_middleware` in `app/auth/cookies.py` compares the two and returns `403`
  on a mismatch. Login and register are exempt.

### RBAC (Role-Based Access Control)

- Authorization based on user role.
- Roles here: `admin`, `sales_manager`, `sales_rep`.
- Enforced by `require_role` / `require_admin` / `require_permissions` in
  `app/auth/dependencies.py`.
- Beyond route guards, list endpoints filter rows by role: a rep sees what they
  own, a manager sees their team (via `team_members`), an admin sees everything.

### Middleware

- Code that runs around each request/response.
- Registered in `app/main.py`; last registered runs first. The chain is:
  error handler → logging → rate limiter → security → CSRF.

### Dependency Injection (DI)

- FastAPI pattern to inject shared logic (auth checks, DB client) into endpoints.
- In this project, `Depends(...)` is used for auth and repository creation.

### Pydantic Schemas

- Typed models for validating request/response data.
- Prevents invalid payloads and enforces field constraints.

### Repository Pattern

- Data access is isolated in repository classes under `app/repositories/`.
- Routers stay focused on API behavior; repositories handle DB operations.

### CORS

- Controls which frontend origins can call this API from browsers.
- Origins are **allow-listed** in `app/main.py`. Because `allow_credentials=True`,
  a wildcard is not permitted — a new frontend domain must be added there
  explicitly or the browser will reject the cookies.

### RLS (Row-Level Security)

- Database-level access policies in PostgreSQL/Supabase.
- Migrations enable RLS on core tables (leads, calls, teams, customers,
  organizations, task deadline alerts, and the AI tables).

## 3) Project Flow In One View

```text
Client
  -> FastAPI app (app/main.py)
  -> Middleware chain (error handler, logging, rate limit, security, CSRF)
  -> Router endpoint (app/routers/*)
  -> Auth dependency (if protected)
  -> Pydantic schema validation (app/schemas/*)
  -> Service layer (app/services/*) for cross-entity logic
  -> Repository (app/repositories/*)
  -> Postgres client/query builder
  -> PostgreSQL tables
  -> JSON response (+ X-Request-ID, rate-limit headers)
```

## 4) Request Lifecycle (protected endpoint example)

Example: `GET /api/leads/`

1. Request enters FastAPI app.
2. Middleware runs:
   - error middleware ensures `X-Request-ID`
   - logging writes start/completion logs
   - rate limiter checks per-IP and per-path budget
   - security checks request size and adds headers
   - CSRF check (mutating requests only — skipped for this `GET`)
3. Auth dependency validates the `access_token` cookie:
   - checks the token blacklist (`revoked_tokens`)
   - verifies JWT signature + claims
   - loads the current user from `agents` (5-minute in-process cache)
   - rejects inactive users with `403`
4. Router applies role scoping, validates query params, calls the repository.
5. Repository executes the DB query through the query client.
6. Response is returned in a consistent JSON shape.

## 5) Auth Flow In This Codebase

All of these set or clear cookies; none return tokens in the body.

- `POST /api/auth/register`
  - creates a new `sales_rep` user, hashes the password
  - returns `{ "user": ... }` and sets the auth cookies

- `POST /api/auth/login`
  - verifies email/password
  - returns `{ "user": ... }` and sets the auth cookies

- `GET /api/auth/me`
  - reads the current user from the access-token cookie
  - also returns the caller's resolved permission set

- `POST /api/auth/refresh`
  - validates the refresh-token cookie (no request body)
  - issues a new pair, blacklists the old refresh token (rotation)

- `POST /api/auth/logout`
  - blacklists both tokens, clears cookies, invalidates the cached user

- `POST /api/auth/forgot-password` / `POST /api/auth/reset-password`
  - emailed single-use reset token, TTL `RESET_TOKEN_TTL_MINUTES`

## 6) Core Data Model (what to memorize)

Identity and access:

- `agents`: backend users, roles, password hash, active flag, settings
- `agent_permissions`: per-user permission overrides
- `revoked_tokens`: invalidated JWT token hashes
- `teams` / `team_members`: manager-to-rep grouping that drives row scoping
- `deleted_users`, `invites`, `failed_invites`, `password_reset_tokens`

CRM core:

- `leads`: primary ingestion entity, scored and owned
- `deals`: created from leads; `won` triggers customer creation
- `organizations`: company records leads/deals hang off
- `customers`: terminal entity, created from won deals
- `tasks`, `notes`: attached to any entity via `entity_type` + `entity_id`
- `tickets`, `ticket_messages`: support threads
- `notifications`, `status_change_logs`, `task_deadline_alerts`
- `call_sessions`, `call_room_tokens`: call module

AI control plane:

- `ai_agents`: registry of logical agents (enabled/status/heartbeat)
- `ai_agent_credentials`: hashed service tokens with scopes
- `ai_agent_runs` / `ai_agent_run_traces`: run records and step traces
- `ai_agent_actions` / `ai_agent_approval_requests`: proposed writes and approvals
- `ai_agent_settings`, `ai_interactions`

Relationship summary:

- one lead -> at most one deal -> at most one customer
- one organization -> many leads and deals
- one customer -> many tickets; one ticket -> many ticket messages
- one agent can own many leads/deals and be assigned many tasks/tickets
- one team -> many members (an agent appears at most once per team)

## 7) Endpoint Cheat Sheet (most used)

- Auth:
  - `POST /api/auth/register`, `POST /api/auth/login`
  - `GET /api/auth/me`, `POST /api/auth/refresh`, `POST /api/auth/logout`

- Leads:
  - `GET /api/leads/`, `POST /api/leads/`
  - `GET /api/leads/{lead_id}/workspace` (aggregated detail payload)
  - `POST /api/leads/{lead_id}/convert-to-deal`

- Deals:
  - `GET /api/deals/`, `GET /api/deals/workspace`
  - `PATCH /api/deals/{deal_id}` (setting `won` creates the customer)

- Tasks / Notes:
  - `GET /api/tasks/`, `GET /api/notes/` (filter by `entity_type` + `entity_id`)

- Dashboard:
  - `GET /api/dashboard/summary`, `GET /api/dashboard/activity`

- AI control plane:
  - `GET /api/agent/control-center`, `GET /api/agent/approvals`
  - `POST /api/agent/approvals/{approval_id}/approve`

- Imports:
  - `POST /api/import/leads`, `/customers`, `/tickets`

## 8) 3-Minute Demo Script

- Start backend and open `/docs`.
- Call `POST /api/auth/login` from the frontend (or curl with a cookie jar) —
  Swagger's "Authorize" button will not help here, since auth is cookie-based
  rather than a bearer header.
- Call `GET /api/leads/` and `GET /api/dashboard/summary`.
- Open the AI Control Center in the UI and walk one run → trace → approval.
- Explain where auth, role scoping, validation, and repository logic are applied.

## 9) Disabled User Detection (frontend behavior)

We need disabled users to lose access quickly. These are the options:

1) Server-push (SSE or WebSocket)
   - Backend publishes a "user_disabled" event to the specific user.
   - Frontend reacts instantly and clears the session.
   - Best long-term scalability, requires persistent connections and auth on the channel.

2) Short-interval polling (**current**)
   - Frontend polls `GET /api/auth/me` every 6 seconds while logged in
     (`src/App.jsx`).
   - If the backend returns `403 Inactive user`, the client clears the session
     and shows the inactive modal.
   - Simple and reliable; load scales with concurrent active users.

3) Token revocation + short-lived access tokens
   - Disable action blacklists active tokens and uses shorter access token TTLs.
   - User is blocked on the next API request, without polling.
   - Lowest steady-state load, but not instant unless requests are frequent.

## 10) CRM Porting Priorities

### Shipped

1) Lead/Deal default status rules
2) Lost reason capture for Lead/Deal
3) Status change logging (`status_change_logs`)
4) Owner assignment rules and manager/admin scope checks
5) Canonical status taxonomy (`app/utils/statuses.py`)

### Later pipeline (documented for follow-up)

1) SLA lifecycle (first response/rolling response, breach tracking)
   - Reason: valuable for support ops, but not required for core CRM CRUD.

2) Lead -> Contact/Organization auto-creation
   - Reason: helpful for CRM completeness, but can be manual without breaking flows.

3) Deal forecasting rules (probability, expected close/value requirements)
   - Reason: analytics-driven; safe to add once basic lifecycle is stable.

4) Exchange rate/multi-currency handling
   - Reason: needed for global sales, not a blocker for initial deployments.

5) Lead enrichment (gravatar/image)
   - Reason: UI polish only; no impact on business logic.

6) Task kanban metadata defaults
   - Reason: UI-specific configuration; can be added after core task CRUD.

## 11) Quick Glossary (backend terms)

- API: contract for how systems communicate.
- Endpoint: one API URL + method.
- Payload: request/response body.
- Schema: typed data contract (validation rules).
- Serialization: converting objects to JSON.
- Authentication: who you are.
- Authorization: what you are allowed to do.
- Hashing: one-way password protection.
- Token revocation: invalidating a token before natural expiry.
- TTL: how long a token/resource remains valid.
- Idempotent: same request repeated gives same effect (for suitable operations).
- Pagination: returning data in chunks (`skip`, `limit`).
- Middleware: pre/post request processing layer.
- Dependency: reusable logic injected into route handlers.
- Repository: abstraction over DB operations.
- RLS: DB-level per-row access policy.

## 12) What Team Members Should Know After 20 Minutes

- Where requests enter and how they move through the backend.
- How cookie auth, CSRF, and refresh-token rotation work in this project.
- Where role checks are enforced — both route guards and row-level scoping.
- Where to add new endpoints, schemas, and repository logic safely.
- Which tables are core for day-to-day CRM operations.
- That the AI service never writes CRM data directly; it proposes actions
  through `/api/agent` and waits for approval.
