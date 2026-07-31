# Frontend Integration Guide

Last Updated: 2026-07-28

This guide explains how frontend teams should connect with the current backend implementation.

Primary API contract document:

- `docs/API.md`

Use this guide for implementation workflow and the API document for exact endpoint contracts.

## 1. Quick Start

1. Set backend base URL:
   - Local: `http://localhost:8000`
   - Production: your current deployment URL
2. Confirm backend health using `GET /health`.
3. Confirm API docs are reachable on `/docs`.
4. Send every request with `credentials: "include"` — auth is cookie-based, so
   there is nothing to store client-side.
5. Add a centralized API client that attaches the CSRF header and refreshes on `401`.

The reference implementation of all of this is
`src/api/client.js` in the frontend repo.

## 2. Important Corrections for Frontend

The current backend uses these methods for updates:

- Customers update: `PATCH /api/customers/{customer_id}`
- Tickets update: `PATCH /api/tickets/{ticket_id}`
- Users update: `PATCH /api/users/{user_id}`

Do not use `PUT` for these routes.

### Canonical Paths (Important)

Use trailing slash for collection routes:

- `GET/POST /api/users/`
- `GET/POST /api/customers/`
- `GET/POST /api/tickets/`

Calling collection endpoints without trailing slash returns a `307` redirect.
Prefer canonical paths — the redirect costs an extra round trip and not every
client replays the body.

Note: team routes are registered **without** a trailing slash
(`/api/admin/teams`).

## 3. Auth Flow (Required)

Auth is **HttpOnly cookies plus double-submit CSRF**. There are no tokens in any
response body and no `Authorization` header anywhere in the flow.

1. Login/register:
   - `POST /api/auth/login`
   - `POST /api/auth/register`
   - Both must be sent with `credentials: "include"`. The response body is
     `{ "user": { ... } }`; the backend sets `access_token`, `refresh_token`,
     and `csrf_token` cookies.
2. Send `credentials: "include"` on every subsequent request.
3. On every `POST`, `PUT`, `PATCH`, and `DELETE`, read the non-HttpOnly
   `csrf_token` cookie and send it as `X-CSRF-Token`. Login and register are
   exempt. A missing or mismatched value returns `403 CSRF token missing or
   invalid`.
4. On `401`, call `POST /api/auth/refresh` once (with credentials and the CSRF
   header). It takes no body and returns `{ "success": true }`; new cookies are
   set automatically.
5. Do not run the refresh flow on `403`.
6. Retry the original request once after a successful refresh.
7. On refresh failure, clear client state and redirect to login.
8. Never write tokens to `localStorage` — the cookies are HttpOnly by design and
   are not readable from JS.

Reading the CSRF cookie:

```js
const csrf = document.cookie
  .match(/(?:^|; )csrf_token=([^;]*)/)?.[1] ?? "";
```

Cookies are `Secure` + `SameSite=None` when the backend runs with `DEBUG=False`,
and `SameSite=Lax` locally. The `refresh_token` cookie is scoped to `/api/auth`.

### CORS

Origins are allow-listed in `app/main.py`, and `allow_credentials=True` means a
wildcard origin is rejected. A new frontend domain must be added there before
cookies will be accepted.

## 4. RBAC Rules Frontend Must Respect

- Admin-only operations:
  - `GET /api/users/`
  - `POST /api/users/`
  - `DELETE /api/users/{user_id}`
  - `DELETE /api/customers/{customer_id}`
  - `DELETE /api/tickets/{ticket_id}`
  - The `/api/admin/*` console and `/api/admin/teams` routes
- Ticket assignment (`assigned_to`) can be changed only by:
  - `admin`
  - `sales_manager`
- Import endpoints can be used only by:
  - `admin`
  - `sales_manager`
- A normal user can fetch/update own user record, but cannot change `role` or `is_active`.
- `POST /api/auth/register` always creates users with role `sales_rep`.
- `DELETE /api/users/{user_id}` is a soft delete (`is_active=false`), not row removal.

### Record-level scoping

List endpoints filter by the caller's role before any query param is applied:

- `sales_rep` sees only records they own.
- `sales_manager` sees their team's records (resolved via `team_members`).
- `admin` sees everything.

So an empty list is often correct rather than a bug — check the caller's role
and team membership before treating it as one.

## 4.1 Data Import Endpoints (CSV/XLSX)

Implemented import routes:

- `POST /api/import/leads`
- `POST /api/import/customers`
- `POST /api/import/tickets`

Request type:

- `multipart/form-data`
- file field key must be `file`

Do **not** set `Content-Type` manually for these; let the browser set the
multipart boundary. The CSRF header is still required.

Limits: `IMPORT_MAX_FILE_BYTES` (default 5 MB) and `IMPORT_MAX_ROWS`
(default 5000).

Supported file types:

- `.csv`
- `.xlsx`
- `.xlsm`

Customers file columns:

- `email` (required)
- `full_name` (required)
- `phone` (optional)
- `company` (optional)
- `status` (optional)
- `notes` (optional)

Tickets file columns:

- `subject` (required)
- `customer_id` (required unless `customer_email` exists)
- `customer_email` (optional)
- `description` (optional)
- `status` (optional)
- `priority` (optional)
- `category` (optional)
- `assigned_to` (optional)

Expected UI behavior:

- Show import summary (`total_rows`, `successful_rows`, `created_count`, `failed_count`).
- If failures exist, show each failed row number and reason.
- Do not fail entire import UI when only some rows fail.

## 5. Error Handling Rules

Backend returns structured errors with `request_id`.

`error.code` may be either a machine string (for validation/custom errors) or
an HTTP status integer (for standard HTTP exceptions).

Example shape:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "request_id": "uuid",
    "timestamp": "2026-04-03T12:00:00+00:00",
    "details": []
  }
}
```

UI handling recommendations:

- `401`: try refresh flow once, then log out
- `403`: show permission/auth message (RBAC, missing/invalid CSRF token, or inactive user)
- `413`: show request too large
- `422`: map field-level errors
- `429`: show retry countdown from `Retry-After`

## 6. Required Frontend Env Variables

The shipped frontend is Vite and reads:

```env
VITE_API_BASE_URL=http://localhost:8000
```

It falls back to `http://localhost:8000` when unset.

## 7. Integration Checklist

- [ ] Login/register succeed and the auth cookies appear in devtools
- [ ] Every request sends `credentials: "include"`
- [ ] Mutating requests send `X-CSRF-Token` from the `csrf_token` cookie
- [ ] Auto-refresh works and retries once
- [ ] Refresh runs on `401` only (not on `403`)
- [ ] Nothing writes tokens to `localStorage`
- [ ] Enum values are aligned with backend
- [ ] PATCH requests are used for updates
- [ ] Collection endpoints use canonical trailing-slash paths
- [ ] RBAC actions are hidden/disabled in UI
- [ ] 422 field errors display correctly in forms
- [ ] 429 and 413 are handled with user-friendly messages
- [ ] Lead/customer/ticket imports work for manager/admin users
- [ ] Import failure rows are visible in UI

## 8. Source of Truth

For payload examples, enums, and every endpoint contract use:

- `docs/API.md`

If backend routes or schemas change, update `docs/API.md` in the same change set.
