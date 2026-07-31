# AutoCRM Backend API Handover

Last Updated: 2026-07-28
Backend Version: 1.0.0

This document is the implementation-accurate API contract for frontend teams.
It reflects the endpoints, payloads, validation rules, and security middleware currently active in the backend.

## 1. Scope and Current Coverage

Implemented and ready for frontend integration:

- Health endpoints
- Authentication (register, login, me, profile, avatar, refresh, logout, forgot/reset password)
- Users (RBAC-protected CRUD + deactivation)
- Customers (CRUD)
- Tickets (CRUD)
- Ticket messages
- Organizations (CRUD)
- Leads (CRUD + scoring, bulk assign, workspace, ingestion, lead-to-deal conversion)
- Deals (CRUD + workspace + deal-to-customer conversion)
- Tasks (CRUD)
- Notes (CRUD)
- Notifications (list, mark read, mark all read)
- Dashboard metrics + activity + latest AI summary
- Data import (CSV/XLSX for customers, tickets, and leads)
- Invites (validate + accept) and admin invite management
- Admin console (overview, activity log, users, deleted users, failed invites, permissions)
- Teams (admin-managed)
- Calls (session start/end, chunked recording upload, recording download)
- AI control plane (`/api/agent`): runs, traces, actions, approvals, settings, AI agent registry, service credentials, RAG snapshot/reconcile
- Request ID, structured errors, rate limiting, and security headers

## 2. Base URLs and API Docs

- Local: `http://localhost:8000`
- Production: use your active deployment URL
- OpenAPI/Swagger: `/docs`
- ReDoc: `/redoc`

CORS origins are allow-listed in `app/main.py`. Because `allow_credentials=True`,
wildcard origins are rejected — a new frontend domain must be added there.

## 3. Authentication Model

- Auth transport: **HttpOnly cookies** (`access_token`, `refresh_token`) with a
  `csrf_token` cookie for double-submit CSRF protection.
- Cookies are the **only** transport for human users. `get_current_user` reads
  the `access_token` cookie and has no `Authorization: Bearer` fallback, so a
  bearer header alone returns `401 Not authenticated`. Tests and tooling must
  set the cookie (see `tests/test_live_http_audit.py`).
- Service-to-service calls from the AI service use the AI headers instead — see
  section 3.1.
- Access token TTL: `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (default 30 minutes)
- Refresh token TTL: `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (default 7 days)
- Refresh token rotation: enabled (old refresh token is blacklisted after refresh)
- Logout invalidation: access token + refresh token are revoked in `revoked_tokens`

### Cookie Scopes

| Cookie          | HttpOnly | Path        | Purpose                        |
| --------------- | -------- | ----------- | ------------------------------ |
| `access_token`  | yes      | `/`         | Authenticates API requests     |
| `refresh_token` | yes      | `/api/auth` | Rotates the access token       |
| `csrf_token`    | no       | `/`         | Read by JS for the CSRF header |

Cookies are `Secure` + `SameSite=None` when `DEBUG=False`, and `SameSite=Lax`
locally.

### Required Headers

- Browser clients: send cookies (`credentials: "include"`), plus
  `X-CSRF-Token: <csrf_token cookie>` on every `POST`, `PUT`, `PATCH`, and
  `DELETE`. Login and register are exempt.
- Non-browser clients: send the `access_token` cookie (e.g. `-b
  "access_token=<jwt>"` with curl) plus the CSRF cookie/header pair on mutating
  requests. There is no bearer-token path for user auth.

### 3.1 AI Service Authentication

Endpoints wrapped in `require_ai_agent_auth` / `require_human_or_ai_agent_auth`
accept service credentials instead of a user cookie:

| Header               | Required | Purpose                                              |
| -------------------- | -------- | ---------------------------------------------------- |
| `X-AI-Service-Token` | yes      | Raw token; matched by SHA-256 hash against `ai_agent_credentials` |
| `X-AI-Agent-Key`     | no       | Runtime attribution only (e.g. `deal_risk_watcher`)  |

The token authenticates the AI service globally, not one logical agent. The
credential must be `is_active` and unexpired; a supplied agent key must resolve
to an enabled, `active` row in `ai_agents` or the request is rejected `403`.
Issue tokens via `POST /api/agent/service-credentials` (Profile Settings →
Developer Mode). When both an AI header and a cookie are present on a
`require_human_or_ai_agent_auth` route, the AI headers win.

Missing or mismatched CSRF tokens return `403 CSRF token missing or invalid`.

### Canonical Collection Paths

Collection routes in this API are defined with trailing slash:

- `/api/users/`
- `/api/customers/`
- `/api/tickets/`
- `/api/organizations/`
- `/api/leads/`
- `/api/deals/`
- `/api/tasks/`
- `/api/notes/`
- `/api/notifications/`

Calling these without the trailing slash returns `307 Temporary Redirect`.
Prefer the canonical paths directly — a redirect hop costs a round trip and not
every client replays the request body on `307`.

Note: team routes are registered without a trailing slash (`/api/admin/teams`).

## 4. Global Middleware Contract

### Request Correlation

- Optional request header: `X-Request-ID`
- If absent, backend generates one.
- Response always includes `X-Request-ID`.

### Rate Limiting

- Configured by:
  - `RATE_LIMIT_ENABLED` (default `True`)
  - `RATE_LIMIT_REQUESTS_PER_MINUTE` (default `100`)
  - `RATE_LIMIT_MAX_QUEUE_SIZE` (default `500`)
- Current strategy: per-IP + per-path, in-memory bucket
- Response headers:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `Retry-After` (only when 429)

### Request Size Guard

- Configured by `MAX_REQUEST_SIZE_BYTES` (default `1048576`)
- Oversized request response: `413`

### Security Headers

When `SECURITY_HEADERS_ENABLED=True`, responses include:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-XSS-Protection: 1; mode=block`
- `Content-Security-Policy`:
  - strict default for API endpoints
  - docs-compatible policy for `/docs` and `/redoc`

## 5. Error Response Contract

Most errors follow this structure:

- `error.code` may be a string machine code (for framework/custom handlers)
  or an HTTP status integer (for standard HTTP exceptions).

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "request_id": "f7d2e9a4-...",
    "timestamp": "2026-04-03T12:00:00.000000+00:00",
    "details": [
      {
        "field": "body.email",
        "message": "Input should be a valid email address",
        "type": "value_error"
      }
    ]
  }
}
```

Common status codes:

- `400` bad request
- `401` unauthorized/invalid token
- `403` forbidden (RBAC, missing/invalid CSRF token, or inactive user)
- `307` temporary redirect (typically path trailing-slash normalization)
- `404` resource not found
- `413` request body too large
- `422` validation error
- `429` rate limit exceeded
- `500` internal server error

## 6. Enums and Domain Values

### Roles

- `admin`
- `sales_manager`
- `sales_rep`

### Customer Status

- `active`
- `inactive`
- `lead`
- `churned`

### Ticket Status

- `open`
- `in_progress`
- `pending`
- `resolved`
- `closed`

### Ticket Priority

- `low`
- `medium`
- `high`
- `urgent`

### Ticket Sender Type

- `customer`
- `agent`
- `ai`

### Lead Status

- Free-text status string
- Default: `new`
- Key statuses:
  - `new`: Newly created lead
  - `qualified`: Lead converted to deal
  - `won`: Deal completed successfully (auto-converted to customer)
  - `lost`: Deal closed without conversion

### Deal Stage

- Free-text stage string
- Default: `prospecting`

### Deal Status

- Free-text status string
- Default: `qualified` (when created from lead conversion)
- Key statuses:
  - `qualified`: Deal created from lead
  - `won`: Deal closed successfully, triggers automatic customer creation
  - `lost`: Deal closed without conversion

### Task Status

- Free-text status string
- Default: `open`

### Task Priority

- Free-text priority string
- Default: `medium`

### Entity Type Fields

- `tasks.entity_type` and `notes.entity_type` are free-text
- Recommended values: `lead`, `deal`, `customer`, `organization`, `ticket`

## 7. Validation and Sanitization Rules

Backend applies schema-level validation and sanitization:

- HTML tags are stripped from text fields.
- Control characters are removed.
- Dangerous SQL-like tokens are blocked for selected fields.
- Field constraints (length/types) are enforced by Pydantic schemas.

Important constraints:

- Password minimum length: `6`
- User full_name: `2..255`
- Customer notes max length: `5000`
- Ticket subject: `3..500`
- Ticket description max length: `5000`
- Ticket category: `2..100`
- Ticket message content: `1..5000`

## 8. Endpoint Reference

## 8.1 Health

### GET /

- Auth: none
- Response `200`:

```json
{
  "message": "Welcome to AutoCRM an Agentic AI Enabled CRM System",
  "status": "running"
}
```

### GET /health

- Auth: none
- Response `200`:

```json
{
  "status": "healthy"
}
```

## 8.2 Authentication (`/api/auth`)

### POST /api/auth/register

- Auth: none
- Request:

```json
{
  "email": "rep@example.com",
  "password": "secure-pass-123",
  "full_name": "Sales Rep"
}
```

- Response `201`:

```json
{
  "user": {
    "id": "uuid",
    "email": "rep@example.com",
    "full_name": "Sales Rep",
    "role": "sales_rep",
    "is_active": true,
    "created_at": "2026-04-03T12:00:00+00:00"
  }
}
```

- Tokens are **not** returned in the body. They are issued only as the
  `access_token`, `refresh_token`, and `csrf_token` cookies.
- Note: newly registered users are always created with role `sales_rep`.

### POST /api/auth/login

- Auth: none
- Request:

```json
{
  "email": "rep@example.com",
  "password": "secure-pass-123"
}
```

- Response `200`: `{ "user": { ... } }` — same shape as register, and sets the
  same auth cookies. Tokens are cookie-only.

### GET /api/auth/me

- Auth: required
- Response `200`:

```json
{
  "id": "uuid",
  "email": "rep@example.com",
  "full_name": "Sales Rep",
  "role": "sales_rep",
  "is_active": true,
  "avatar_url": "http://localhost:8000/static/avatars/<file>",
  "created_at": "2026-04-03T12:00:00+00:00"
}
```

- Response also includes the caller's resolved permission set.

### PATCH /api/auth/profile

- Auth: required
- Request (partial): `full_name`, `phone`, and other self-editable profile fields
- Response `200`: `UserResponse`

### POST /api/auth/avatar

- Auth: required
- Content type: `multipart/form-data`, field name `file`
- Allowed types: JPEG, PNG, WebP, GIF
- Response `200`: `UserResponse` with the updated `avatar_url`

### DELETE /api/auth/avatar

- Auth: required
- Response `200`: `UserResponse` with `avatar_url` cleared

### POST /api/auth/refresh

- Auth: none (reads the `refresh_token` cookie)
- Request: no body. A missing cookie returns `401 Missing refresh token`; a
  reused/blacklisted one returns `401 Refresh token has been invalidated`.

- Response `200`:

```json
{
  "success": true
}
```

- Rotates all auth cookies and revokes the previous refresh token. No tokens
  appear in the response body.
- The `refresh_token` cookie is scoped to `/api/auth`, so refresh must be called on that path.

### POST /api/auth/logout

- Auth: required
- Request: no body. Both the access and refresh tokens are read from cookies and
  blacklisted in `revoked_tokens`.

- Response `200`:

```json
{
  "success": true,
  "message": "Successfully logged out"
}
```

- Revokes tokens, clears all auth cookies, and invalidates the cached user.

### POST /api/auth/forgot-password

- Auth: none
- Request: `{ "email": "rep@example.com" }`
- Response `200`: always a generic success message (does not disclose whether the account exists)
- Sends a reset link to `FRONTEND_BASE_URL`; token TTL is `RESET_TOKEN_TTL_MINUTES` (default 30)

### POST /api/auth/reset-password

- Auth: none
- Request: `{ "token": "<reset-token>", "password": "secure-pass-123" }`
- Response `200`: `{ "message": "Password reset successful" }`; the token is single-use

## 8.3 Users (`/api/users`)

### GET /api/users/

- Auth: required
- Role: `admin`
- Response `200`: array of `UserResponse`

### GET /api/users/{user_id}

- Auth: required
- Role: `admin` or self
- Response `200`: `UserResponse`

### POST /api/users/

- Auth: required
- Role: `admin`
- Request:

```json
{
  "email": "new.user@example.com",
  "full_name": "New User",
  "role": "sales_rep",
  "password": "secure-pass-123"
}
```

- Response `201`: `UserResponse`

### PATCH /api/users/{user_id}

- Auth: required
- Role: self or `admin`
- Rule: only `admin` can change `role` or `is_active`
- Request (partial):

```json
{
  "full_name": "Updated Name",
  "password": "new-password-123"
}
```

- Response `200`: `UserResponse`

### DELETE /api/users/{user_id}

- Auth: required
- Role: `admin`
- Behavior: soft delete (`is_active=false`)
- Record is not removed from the database.
- Response `204`: empty body

## 8.4 Customers (`/api/customers`)

### GET /api/customers/

- Auth: required
- Query params:
  - `skip` (default `0`)
  - `limit` (default `100`)
  - `status` (`active|inactive|lead|churned`)
- Response `200`: array of `CustomerResponse`

### GET /api/customers/{customer_id}

- Auth: required
- Response `200`: `CustomerResponse`

### POST /api/customers/

- Auth: required
- Request:

```json
{
  "email": "customer@example.com",
  "full_name": "Customer Name",
  "phone": "+1 555 123 4567",
  "company": "Acme Corp",
  "status": "active",
  "notes": "Important account"
}
```

- Response `201`: `CustomerResponse`

### PATCH /api/customers/{customer_id}

- Auth: required
- Request (partial):

```json
{
  "status": "inactive",
  "notes": "Moved to inactive"
}
```

- Response `200`: `CustomerResponse`

### DELETE /api/customers/{customer_id}

- Auth: required
- Role: `admin`
- Response `204`: empty body

## 8.5 Tickets (`/api/tickets`)

### GET /api/tickets/

- Auth: required
- Query params:
  - `skip` (default `0`)
  - `limit` (default `100`)
  - `status` (`open|in_progress|pending|resolved|closed`)
  - `priority` (`low|medium|high|urgent`)
  - `customer_id` (UUID)
- Response `200`: array of `TicketResponse`

### GET /api/tickets/{ticket_id}

- Auth: required
- Response `200`: `TicketResponse`

### POST /api/tickets/

- Auth: required
- Request:

```json
{
  "customer_id": "uuid",
  "subject": "Login issue",
  "description": "User cannot login",
  "status": "open",
  "priority": "high",
  "category": "support"
}
```

- Response `201`: `TicketResponse`

### PATCH /api/tickets/{ticket_id}

- Auth: required
- Request (partial):

```json
{
  "status": "in_progress",
  "assigned_to": "uuid"
}
```

- RBAC rule: `assigned_to` can be updated only by `sales_manager` or `admin`.
- Response `200`: `TicketResponse`

### DELETE /api/tickets/{ticket_id}

- Auth: required
- Role: `admin`
- Response `204`: empty body

## 8.6 Ticket Messages

### GET /api/tickets/{ticket_id}/messages

- Auth: required
- Response `200`: array of `TicketMessageResponse`

### POST /api/tickets/{ticket_id}/messages

- Auth: required
- Request:

```json
{
  "content": "Please share screenshot",
  "sender_type": "agent",
  "sender_id": "uuid"
}
```

- Response `201`: `TicketMessageResponse`

## 8.7 Data Import (`/api/import`)

Import endpoints are designed for test-data onboarding and migration-style bulk insert/update flows.
Both endpoints support:

- `multipart/form-data`
- file field name: `file`
- supported file extensions: `.csv`, `.xlsx`, `.xlsm`
- row-level partial success (one bad row does not fail the full file)

RBAC:

- Allowed roles: `sales_manager`, `admin`

### Common Response Shape

```json
{
  "entity": "customers",
  "file_name": "customers.csv",
  "total_rows": 10,
  "successful_rows": 9,
  "created_count": 7,
  "updated_count": 2,
  "failed_count": 1,
  "failures": [
    {
      "row_number": 6,
      "reason": "...validation or lookup error..."
    }
  ]
}
```

### POST /api/import/customers

- Auth: required
- Role: `sales_manager` or `admin`
- Content type: `multipart/form-data`
- Field: `file`

CSV/XLSX column contract for customer import:

- `email` (required)
- `full_name` (required)
- `phone` (optional)
- `company` (optional)
- `status` (optional, defaults to `active`)
- `notes` (optional)

Import behavior:

- Existing customer by matching `email` is updated.
- New customer is created when email does not exist.

### POST /api/import/tickets

- Auth: required
- Role: `sales_manager` or `admin`
- Content type: `multipart/form-data`
- Field: `file`

CSV/XLSX column contract for ticket import:

- `subject` (required)
- `customer_id` (required unless `customer_email` is provided)
- `customer_email` (optional customer lookup alternative)
- `description` (optional)
- `status` (optional, defaults to `open`)
- `priority` (optional, defaults to `medium`)
- `category` (optional)
- `assigned_to` (optional)

Import behavior:

- Ticket rows are created (no upsert currently for tickets).
- If `customer_id` is missing and `customer_email` is provided, customer is resolved by email.
- If customer lookup fails, row is reported in `failures`.

## 8.8 Leads (`/api/leads`)

Scoping: `sales_rep` sees only owned leads; `sales_manager` sees their team's
leads (via `team_members`); `admin` sees all. Passing `owner_id` narrows within
whatever the caller may already see.

| Method   | Path                              | Notes                                                     |
| -------- | --------------------------------- | --------------------------------------------------------- |
| `GET`    | `/api/leads/`                     | Filters: `skip`, `limit`, `status`, `owner_id`, `organization_id`, `source`, `search` |
| `POST`   | `/api/leads/`                     | Creates a lead; `201`                                     |
| `GET`    | `/api/leads/{lead_id}`            | Single lead                                               |
| `PATCH`  | `/api/leads/{lead_id}`            | Partial update                                            |
| `DELETE` | `/api/leads/{lead_id}`            | `204`                                                     |
| `GET`    | `/api/leads/{lead_id}/workspace`  | Aggregated detail payload (lead + tasks + notes + activity) in one round trip |
| `GET`    | `/api/leads/{lead_id}/owner`      | Resolved owner record                                     |
| `GET`    | `/api/leads/{lead_id}/ai-history` | AI runs/actions recorded against this lead                |
| `GET`    | `/api/leads/{lead_id}/emails`     | Logged email activity                                     |
| `GET`    | `/api/leads/{lead_id}/calls`      | `CallSessionResponse[]`                                   |
| `GET`    | `/api/leads/assignment-reps`      | Reps the caller may assign to                             |
| `POST`   | `/api/leads/assign-bulk`          | Bulk owner reassignment; returns updated leads            |
| `POST`   | `/api/leads/{lead_id}/convert-to-deal` | Creates a deal, sets lead `qualified`; `201`         |
| `POST`   | `/api/leads/{lead_id}/discard-deal` | Marks the lead's deal lost                              |
| `POST`   | `/api/leads/{lead_id}/score/recalculate` | Recomputes the lead score                          |
| `POST`   | `/api/leads/ingest`               | External/inbound lead intake; `201`                       |

## 8.9 Deals (`/api/deals`)

| Method   | Path                                    | Notes                                                    |
| -------- | --------------------------------------- | -------------------------------------------------------- |
| `GET`    | `/api/deals/`                           | Filters: `skip`, `limit`, `stage`, `owner_id`, `organization_id`, `lead_id` |
| `POST`   | `/api/deals/`                           | `201`                                                    |
| `GET`    | `/api/deals/workspace`                  | Pipeline board payload for all visible deals             |
| `GET`    | `/api/deals/{deal_id}`                  | Single deal                                              |
| `PATCH`  | `/api/deals/{deal_id}`                  | Partial update; moving to `won` triggers customer creation |
| `DELETE` | `/api/deals/{deal_id}`                  | `204`                                                    |
| `GET`    | `/api/deals/{deal_id}/workspace`        | Aggregated detail payload                                |
| `GET`    | `/api/deals/{deal_id}/ai-history`       | AI runs/actions for this deal                            |
| `GET`    | `/api/deals/assignment-owners`          | Owners the caller may assign to                          |
| `POST`   | `/api/deals/{deal_id}/convert-to-customer` | `201` `CustomerResponse`                              |

## 8.10 Organizations (`/api/organizations`)

| Method   | Path                                             | Notes                       |
| -------- | ------------------------------------------------ | --------------------------- |
| `GET`    | `/api/organizations/`                            | Filters: `skip`, `limit`    |
| `POST`   | `/api/organizations/`                            | `201`                       |
| `GET`    | `/api/organizations/{organization_id}`           | Single org                  |
| `PATCH`  | `/api/organizations/{organization_id}`           | Partial update              |
| `DELETE` | `/api/organizations/{organization_id}`           | `204`                       |
| `GET`    | `/api/organizations/{organization_id}/workspace` | Org + related leads/deals   |

## 8.11 Tasks (`/api/tasks`)

| Method   | Path                    | Notes                                                                 |
| -------- | ----------------------- | --------------------------------------------------------------------- |
| `GET`    | `/api/tasks/`           | Filters: `skip`, `limit`, `status`, `assigned_to`, `entity_type`, `entity_id`, `priority` |
| `POST`   | `/api/tasks/`           | `201`                                                                 |
| `GET`    | `/api/tasks/{task_id}`  | Single task                                                           |
| `PATCH`  | `/api/tasks/{task_id}`  | Partial update                                                        |
| `DELETE` | `/api/tasks/{task_id}`  | `204`                                                                 |

Callers without manage-all rights are restricted to tasks on entities they can
access; lead-scoped requests are authorization-checked against lead ownership.

## 8.12 Notes (`/api/notes`)

| Method   | Path                    | Notes                                                            |
| -------- | ----------------------- | ---------------------------------------------------------------- |
| `GET`    | `/api/notes/`           | Filters: `skip`, `limit`, `entity_type`, `entity_id`, `author_id` |
| `POST`   | `/api/notes/`           | `201`                                                            |
| `GET`    | `/api/notes/{note_id}`  | Single note                                                      |
| `PATCH`  | `/api/notes/{note_id}`  | Partial update                                                   |
| `DELETE` | `/api/notes/{note_id}`  | `204`                                                            |

## 8.13 Notifications (`/api/notifications`)

| Method  | Path                                      | Notes                          |
| ------- | ----------------------------------------- | ------------------------------ |
| `GET`   | `/api/notifications/`                     | Caller's notifications         |
| `PATCH` | `/api/notifications/{notification_id}/read` | Mark one read                |
| `PATCH` | `/api/notifications/read-all`             | Mark all read                  |

## 8.14 Dashboard (`/api/dashboard`)

| Method | Path                              | Notes                                              |
| ------ | --------------------------------- | -------------------------------------------------- |
| `GET`  | `/api/dashboard/summary`          | Role-scoped KPI metrics                            |
| `GET`  | `/api/dashboard/activity`         | Recent activity feed                               |
| `GET`  | `/api/dashboard/ai-summary/latest` | Most recent AI daily summary for the caller       |

## 8.15 Calls (`/api/calls`)

Recordings upload in chunks and are written under `CALL_RECORDINGS_DIR`. Chunk
size is capped by `CALL_RECORDING_CHUNK_MAX_BYTES` (default 5 MB) and total size
by `CALL_RECORDING_MAX_BYTES` (default 100 MB).

| Method | Path                                    | Notes                                       |
| ------ | --------------------------------------- | ------------------------------------------- |
| `POST` | `/api/calls/start`                      | Opens a call session, returns room token    |
| `POST` | `/api/calls/{call_id}/end`              | Closes the session                          |
| `POST` | `/api/calls/{call_id}/recording/start`  | Begins a chunked upload                     |
| `POST` | `/api/calls/{call_id}/recording/chunks` | Uploads one chunk (`multipart/form-data`)   |
| `POST` | `/api/calls/{call_id}/recording/complete` | Finalizes; notifies the AI service for transcription |
| `POST` | `/api/calls/{call_id}/recording`        | Single-shot recording upload                |
| `GET`  | `/api/calls/{call_id}/recording/file`   | Streams the stored recording                |

Room token TTL is `CALL_ROOM_TOKEN_TTL_MINUTES` (default 15).

## 8.16 Invites (`/api/invites`)

| Method | Path                      | Notes                                                  |
| ------ | ------------------------- | ------------------------------------------------------ |
| `GET`  | `/api/invites/validate`   | Auth: none. Validates an invite token before signup    |
| `POST` | `/api/invites/accept`     | Auth: none. Accepts the invite and sets a password      |

Invite token TTL is `INVITE_TOKEN_TTL_HOURS` (default 72). Invites are created
from the admin routes below and delivered via Mailjet.

## 8.17 Admin (`/api/admin`)

All routes require `admin` unless noted.

| Method   | Path                                                | Notes                                    |
| -------- | --------------------------------------------------- | ---------------------------------------- |
| `GET`    | `/api/admin/overview`                               | Tenant-wide metrics                      |
| `GET`    | `/api/admin/activity-log`                           | Audit/activity log                       |
| `GET`    | `/api/admin/users`                                  | All users                                |
| `POST`   | `/api/admin/users`                                  | Creates a user and sends an invite       |
| `PATCH`  | `/api/admin/users/{user_id}`                        | Update role/status/profile               |
| `DELETE` | `/api/admin/users/{user_id}`                        | Soft delete; recorded in `deleted_users` |
| `GET`    | `/api/admin/deleted-users`                          | Previously deleted users                 |
| `POST`   | `/api/admin/invites/{user_id}/revoke`               | Revokes a pending invite                 |
| `GET`    | `/api/admin/failed-invites`                         | Invites whose delivery failed            |
| `POST`   | `/api/admin/failed-invites/{failed_id}/reinvite`    | Retry delivery                           |
| `DELETE` | `/api/admin/failed-invites/{failed_id}`             | Discard the record                       |
| `GET`    | `/api/admin/users/{user_id}/permissions`            | Effective permission set                 |
| `PUT`    | `/api/admin/users/{user_id}/permissions`            | Replace permission overrides             |

## 8.18 Teams (`/api/admin/teams`)

Registered **without** a trailing slash.

| Method   | Path                                            | Notes                          |
| -------- | ----------------------------------------------- | ------------------------------ |
| `GET`    | `/api/admin/teams`                              | All teams                      |
| `POST`   | `/api/admin/teams`                              | Create a team                  |
| `GET`    | `/api/admin/teams/mine`                         | Teams the caller manages       |
| `GET`    | `/api/admin/teams/{team_id}`                    | Single team with members       |
| `PATCH`  | `/api/admin/teams/{team_id}`                    | Rename / reassign manager      |
| `DELETE` | `/api/admin/teams/{team_id}`                    | Delete team                    |
| `POST`   | `/api/admin/teams/{team_id}/members`            | Add a member                   |
| `DELETE` | `/api/admin/teams/{team_id}/members/{agent_id}` | Remove a member                |

A given agent may appear at most once per team (unique constraint).

## 8.19 AI Control Plane (`/api/agent`)

The backend is the source of truth for AI runs, traces, actions, and approvals.
Routes marked **service** accept `X-AI-Service-Token` (section 3.1); the rest are
cookie-authenticated UI routes, most of them admin-only.

Runs and traces:

| Method  | Path                                | Notes                                        |
| ------- | ----------------------------------- | -------------------------------------------- |
| `POST`  | `/api/agent/runs`                   | service — create a run with a stable external ID |
| `GET`   | `/api/agent/runs`                   | Paginated run list                           |
| `GET`   | `/api/agent/runs/{run_id}`          | Single run                                   |
| `PATCH` | `/api/agent/runs/{run_id}`          | service — update status/result               |
| `POST`  | `/api/agent/runs/{run_id}/trace`    | service — append a trace step                |
| `GET`   | `/api/agent/runs/{run_id}/trace`    | Ordered trace steps                          |
| `GET`   | `/api/agent/control-center`         | Combined control-center payload              |

Actions and approvals:

| Method | Path                                        | Notes                                       |
| ------ | ------------------------------------------- | ------------------------------------------- |
| `POST` | `/api/agent/actions`                        | service — dispatch a proposed action        |
| `GET`  | `/api/agent/approvals`                      | Pending approval requests                   |
| `POST` | `/api/agent/approvals/{approval_id}/approve` | Approve and execute the CRM write          |
| `POST` | `/api/agent/approvals/{approval_id}/reject` | Reject the proposal                         |

Settings, registry, and credentials:

| Method   | Path                                                     | Notes                              |
| -------- | -------------------------------------------------------- | ---------------------------------- |
| `GET`    | `/api/agent/settings`                                    | Per-agent-type settings            |
| `PATCH`  | `/api/agent/settings/{agent_type}`                       | Update one agent type              |
| `GET`    | `/api/agent/ai-agents`                                   | AI agent registry                  |
| `PATCH`  | `/api/agent/ai-agents/{agent_key}`                       | Enable/disable, change status      |
| `GET`    | `/api/agent/ai-agents/runtime`                           | Runtime/heartbeat view             |
| `POST`   | `/api/agent/ai-service/heartbeat`                        | service — liveness ping            |
| `GET`    | `/api/agent/service-credentials`                         | List issued credentials (no raw tokens) |
| `POST`   | `/api/agent/service-credentials`                         | Issue a credential; raw token returned **once** |
| `DELETE` | `/api/agent/service-credentials/{credential_id}`         | Revoke                             |
| `GET`    | `/api/agent/ai-agents/{agent_key}/credentials`           | Credentials scoped to an agent     |
| `POST`   | `/api/agent/ai-agents/{agent_key}/credentials`           | Issue agent-scoped credential      |
| `DELETE` | `/api/agent/ai-agents/{agent_key}/credentials/{credential_id}` | Revoke                       |

Workflow data feeds (all **service**, consumed by the AI service scheduler):

| Method | Path                                              | Notes                                        |
| ------ | ------------------------------------------------- | -------------------------------------------- |
| `GET`  | `/api/agent/users/summary-candidates`             | Users due a daily summary                    |
| `GET`  | `/api/agent/users/{user_id}/summary-context`      | Role-scoped context for that user's summary  |
| `GET`  | `/api/agent/leads/stale-candidates`               | Leads needing a nudge                        |
| `POST` | `/api/agent/leads/score/sweep`                    | Triggers a lead-score recompute sweep        |
| `GET`  | `/api/agent/deals/risk-candidates`                | Deals to evaluate for risk                   |
| `GET`  | `/api/agent/tasks/deadline-candidates`            | Tasks approaching their deadline             |
| `POST` | `/api/agent/tasks/deadline-alerts`                | Records deadline alert output                |
| `POST` | `/api/agent/tasks/deadline-sweep`                 | Runs the rule-based deadline sweep           |
| `GET`  | `/api/agent/memory/{entity_type}/{entity_id}`     | Prior AI actions for an entity               |
| `GET`  | `/api/agent/entity-snapshot/{entity_type}/{entity_id}` | Current entity state for prompt context |
| `GET`  | `/api/agent/rag/snapshot`                         | CRM documents for RAG indexing               |
| `POST` | `/api/agent/rag/reconcile`                        | Reconciles index state with the backend      |
| `GET`  | `/api/agent/team-stats`                           | Manager-scoped team AI stats                 |

## 9. Frontend Integration Playbook

## 9.1 Recommended Auth Flow

1. Login/register with `credentials: "include"`; the backend sets the auth cookies.
2. Send cookies on every request and `X-CSRF-Token` on mutating requests.
3. On `401`, call `/api/auth/refresh` once (also with credentials).
4. Do not run refresh flow on `403`; treat it as a permission, CSRF, or inactive-user problem.
5. Retry the original request once after a successful refresh.
6. If refresh fails, clear client state and redirect to login.
7. Do not store tokens in `localStorage` — the cookies are HttpOnly by design.

## 9.1.1 File Upload Note (Import and Avatar Endpoints)

For `/api/import/*`, `/api/auth/avatar`, and call-recording uploads, use `FormData`:

```ts
const formData = new FormData();
formData.append("file", fileInput.files[0]);

await fetch(`${API_BASE}/api/import/customers`, {
  method: "POST",
  credentials: "include",
  headers: {
    "X-CSRF-Token": readCookie("csrf_token"),
  },
  body: formData,
});
```

Do not manually set `Content-Type` when sending `FormData`; browser sets multipart boundary automatically.

## 9.2 Example TypeScript API Client

```ts
const API_BASE =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function readCookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`))
    ?.split("=")[1];
}

async function apiFetch(path: string, init: RequestInit = {}, retry = true) {
  const method = (init.method || "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };

  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrf = readCookie("csrf_token");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status !== 401 || !retry) return response;

  const refreshRes = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!refreshRes.ok) return response;

  return apiFetch(path, init, false);
}
```

## 9.3 Frontend Error Handling Matrix

- `400`: show request correction message
- `401`: trigger refresh flow or logout
- `403`: show permission denied UI (also check the CSRF header)
- `404`: show not found/empty state
- `413`: show payload too large message
- `422`: map `error.details` to form fields
- `429`: read `Retry-After` and show retry countdown
- `500`: show generic server error banner

## 10. CRM Workflow

The AutoCRM follows a strict lead-to-deal-to-customer conversion workflow, matching the reference CRM (Frappe) pattern.

### Lead Lifecycle

1. **Lead Creation**
   - Leads are created via:
     - Manual POST `/api/leads/` creation
     - CSV/Excel import via `/api/import/leads`
     - Live payload ingestion via `/api/leads/ingest`
   - Initial status: `new` or custom status from import
   - A lead stays a lead until explicitly converted

2. **Lead-to-Deal Conversion** (Manual)
   - Endpoint: `POST /api/leads/{lead_id}/convert-to-deal`
   - Auth: any authenticated user (`require_auth`). There is no additional role
     guard on this route — access is bounded by which leads the caller can see.
   - Payload:
     ```json
     {
       "stage": "prospecting",
       "value": 50000.0,
       "currency": "USD",
       "expected_close_at": "2026-06-30T00:00:00Z",
       "owner_id": "optional-uuid",
       "organization_id": "optional-uuid"
     }
     ```
   - Response: Created deal with `status="qualified"`
   - Side effects:
     - Lead is marked with `converted=true`
     - Lead status is updated to `"qualified"`

### Deal Lifecycle

3. **Deal Status Updates** (with automatic customer creation)
   - Endpoint: `PATCH /api/deals/{deal_id}`
   - Updatable fields: `status`, `stage`, `value`, `currency`, `expected_close_at`, `closed_at`, `lost_reason`
   - When `status` changes to `"won"`:
     - Deal is automatically converted to customer
     - `closed_at` is auto-set to current timestamp
     - A new customer record is created with:
       - `full_name`: From lead name (or deal stage fallback)
       - `email`: From lead email (or generated placeholder)
       - `phone`: From lead phone (if available)
       - `company`: From lead company (if available)
       - `status`: `"active"`
       - `notes`: "Converted from deal {deal_id}"
   - When `status` changes to `"lost"`:
     - `closed_at` is auto-set to current timestamp
     - No customer record is created

4. **Manual Deal-to-Customer Conversion**
   - Endpoint: `POST /api/deals/{deal_id}/convert-to-customer`
   - Only works if deal `status="won"`
   - Returns: Created customer record
   - Response `400` if deal status is not `"won"`
   - If customer already created, returns existing customer

### Customer Lifecycle

- Customers are created **only** when:
  1. Explicitly via `POST /api/customers/`
  2. Automatically when deal status becomes `"won"`
- A customer is a terminal entity (no further conversions)
- A customer cannot be converted back to a lead

### Key Differences from Old Workflow

**Before:**
- Leads and customers were treated as interchangeable
- CSV import created customers directly
- No explicit deal lifecycle

**Now:**
- Leads are primary ingestion entity
- Deals are explicit, status-driven workflow
- Customers are created only when deal is won
- Clear status semantics: lead → deal → customer

## 11. Frontend QA Checklist

- Login and register set the auth cookies (visible in devtools → Application → Cookies).
- Protected calls send `credentials: "include"`; mutating calls send `X-CSRF-Token`.
- Auto-refresh works on `401` and retries the original request once.
- Role-protected screens hide unauthorized actions.
- `PATCH` methods are used where required (not `PUT`).
- Rate-limit and validation errors are user-friendly in UI.
- Logout clears client state; server revokes both tokens and clears cookies.
- CSV import works for leads.
- Connected site payload ingestion works for leads.
- Excel import works for tickets.
- Partial failures are displayed with row number and reason.
- Lead-to-deal conversion marks lead as converted with status="qualified".
- Deal status update to "won" automatically creates customer.
- Deal status update to "lost" closes deal without customer creation.
- Customers are never created from leads directly (only via won deals).

## 12. Notes for Maintainers

- Use this file as the source of truth for endpoint contracts.
- Re-export OpenAPI spec from `/openapi.json` for generated clients if needed.
- Keep frontend enum values synchronized with section 6.
- If backend contracts change, bump API docs and notify frontend team in the same PR.
- CRM Workflow (section 10) defines the lead → deal → customer conversion rules.
- Auth is cookie-only for users; there is no bearer-token path. See section 3.
