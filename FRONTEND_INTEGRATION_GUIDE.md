# Frontend Integration Guide

Last Updated: 2026-04-03

This guide explains how frontend teams should connect with the current backend implementation.

Primary API contract document:

- `docs/API.md`

Use this guide for implementation workflow and the API document for exact endpoint contracts.

## 1. Quick Start

1. Set backend base URL:
   - Local: `http://localhost:8000`
   - Production: `https://autocrmbackend-production-f017.up.railway.app`
2. Confirm backend health using `GET /health`.
3. Confirm API docs are reachable on `/docs`.
4. Implement auth storage for access and refresh tokens.
5. Add a centralized API client with automatic token refresh.

## 2. Important Corrections for Frontend

The current backend uses these methods for updates:

- Customers update: `PATCH /api/customers/{customer_id}`
- Tickets update: `PATCH /api/tickets/{ticket_id}`
- Users update: `PATCH /api/users/{user_id}`

Do not use `PUT` for these routes.

## 3. Auth Flow (Required)

1. Login/register:
   - `POST /api/auth/login`
   - `POST /api/auth/register`
2. Store returned `access_token` and `refresh_token`.
3. Send `Authorization: Bearer <access_token>` for protected endpoints.
4. On `401`, call `POST /api/auth/refresh`.
5. Replace both tokens with returned values (rotation).
6. Retry the failed request once.
7. On refresh failure, clear session and redirect to login.

## 4. RBAC Rules Frontend Must Respect

- Admin-only operations:
  - `GET /api/users/`
  - `POST /api/users/`
  - `DELETE /api/users/{user_id}`
  - `DELETE /api/customers/{customer_id}`
  - `DELETE /api/tickets/{ticket_id}`
- Ticket assignment (`assigned_to`) can be changed only by:
  - `admin`
  - `sales_manager`
- Import endpoints can be used only by:
  - `admin`
  - `sales_manager`
- A normal user can fetch/update own user record, but cannot change `role` or `is_active`.

## 4.1 Data Import Endpoints (CSV/XLSX)

Implemented import routes:

- `POST /api/import/customers`
- `POST /api/import/tickets`

Request type:

- `multipart/form-data`
- file field key must be `file`

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

Example shape:

```json
{
  "success": false,
  "error": {
    "code": 422,
    "message": "Request validation failed",
    "request_id": "uuid",
    "timestamp": "2026-04-03T12:00:00+00:00",
    "details": []
  }
}
```

UI handling recommendations:

- `401`: try refresh flow
- `403`: show permission denied message
- `413`: show request too large
- `422`: map field-level errors
- `429`: show retry countdown from `Retry-After`

## 6. Required Frontend Env Variables

Use one of these based on your stack:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
# or
VITE_API_BASE_URL=http://localhost:8000
# or
REACT_APP_API_BASE_URL=http://localhost:8000
```

## 7. Integration Checklist

- [ ] Login/register works and stores tokens
- [ ] Protected requests include bearer token
- [ ] Auto-refresh works and retries once
- [ ] Enum values are aligned with backend
- [ ] PATCH requests are used for updates
- [ ] RBAC actions are hidden/disabled in UI
- [ ] 422 field errors display correctly in forms
- [ ] 429 and 413 are handled with user-friendly messages
- [ ] Customer CSV import works for manager/admin users
- [ ] Ticket Excel import works for manager/admin users
- [ ] Import failure rows are visible in UI

## 8. Source of Truth

For payload examples, enums, and every endpoint contract use:

- `docs/API.md`

If backend routes or schemas change, update `docs/API.md` in the same change set.
