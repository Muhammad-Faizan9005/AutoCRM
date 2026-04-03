# AutoCRM Backend API Handover

Last Updated: 2026-04-03
Backend Version: 1.0.0 (Week 1 baseline)

This document is the implementation-accurate API contract for frontend teams.
It reflects the endpoints, payloads, validation rules, and security middleware currently active in the backend.

## 1. Scope and Current Coverage

Implemented and ready for frontend integration:

- Health endpoints
- Authentication (register, login, me, refresh, logout)
- Users (RBAC-protected CRUD + deactivation)
- Customers (CRUD)
- Tickets (CRUD)
- Ticket messages
- Data import (CSV/XLSX for customers and tickets)
- Request ID, structured errors, rate limiting, and security headers

Not yet implemented in this backend version:

- Telephony endpoints
- AI endpoints
- Notification/activity timeline endpoints

## 2. Base URLs and API Docs

- Local: `http://localhost:8000`
- Production (current deployment): `https://autocrmbackend-production-f017.up.railway.app`
- OpenAPI/Swagger: `/docs`
- ReDoc: `/redoc`

## 3. Authentication Model

- Auth type: JWT Bearer tokens
- Access token TTL: `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (default 30 minutes)
- Refresh token TTL: `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (default 7 days)
- Refresh token rotation: enabled (old refresh token is blacklisted after refresh)
- Logout invalidation: access token + optional refresh token can be revoked

### Required Header for Protected Endpoints

`Authorization: Bearer <access_token>`

## 4. Global Middleware Contract

### Request Correlation

- Optional request header: `X-Request-ID`
- If absent, backend generates one.
- Response always includes `X-Request-ID`.

### Rate Limiting

- Configured by:
  - `RATE_LIMIT_ENABLED` (default `True`)
  - `RATE_LIMIT_REQUESTS_PER_MINUTE` (default `120`)
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
- `403` forbidden (RBAC)
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
  "message": "Welcome to AutoCRM API",
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
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer",
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

### POST /api/auth/login

- Auth: none
- Request:

```json
{
  "email": "rep@example.com",
  "password": "secure-pass-123"
}
```

- Response `200`: same shape as register.

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
  "created_at": "2026-04-03T12:00:00+00:00"
}
```

### POST /api/auth/refresh

- Auth: none (uses refresh token payload)
- Request:

```json
{
  "refresh_token": "<jwt>"
}
```

- Response `200`:

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### POST /api/auth/logout

- Auth: required
- Request body is optional. If provided, refresh token is also revoked.

```json
{
  "refresh_token": "<jwt>"
}
```

- Response `200`:

```json
{
  "success": true,
  "message": "Successfully logged out"
}
```

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

## 9. Frontend Integration Playbook

## 9.1 Recommended Auth Flow

1. Login/register and store `access_token` + `refresh_token`.
2. Send bearer token on all protected requests.
3. On `401`, call `/api/auth/refresh` once.
4. Replace stored tokens with rotated values.
5. Retry original request once.
6. If refresh fails, clear session and redirect to login.

## 9.1.1 File Upload Note (Import Endpoints)

For `/api/import/*` endpoints, use `FormData` instead of JSON:

```ts
const formData = new FormData();
formData.append("file", fileInput.files[0]);

await fetch(`${API_BASE}/api/import/customers`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${accessToken}`,
  },
  body: formData,
});
```

Do not manually set `Content-Type` when sending `FormData`; browser sets multipart boundary automatically.

## 9.2 Example TypeScript API Client

```ts
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function apiFetch(path: string, init: RequestInit = {}, retry = true) {
  const accessToken = localStorage.getItem("access_token");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (response.status !== 401 || !retry) return response;

  const refreshToken = localStorage.getItem("refresh_token");
  if (!refreshToken) return response;

  const refreshRes = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!refreshRes.ok) return response;
  const refreshData = await refreshRes.json();
  localStorage.setItem("access_token", refreshData.access_token);
  localStorage.setItem("refresh_token", refreshData.refresh_token);

  return apiFetch(path, init, false);
}
```

## 9.3 Frontend Error Handling Matrix

- `400`: show request correction message
- `401`: trigger refresh flow or logout
- `403`: show permission denied UI
- `404`: show not found/empty state
- `413`: show payload too large message
- `422`: map `error.details` to form fields
- `429`: read `Retry-After` and show retry countdown
- `500`: show generic server error banner

## 10. Frontend QA Checklist

- Login and register both store tokens correctly.
- Protected calls include bearer token.
- Auto-refresh works and retries original request.
- Role-protected screens hide unauthorized actions.
- `PATCH` methods are used where required (not `PUT`).
- Rate-limit and validation errors are user-friendly in UI.
- Logout clears local session and revokes current token.
- CSV import works for customers.
- Excel import works for tickets.
- Partial failures are displayed with row number and reason.

## 11. Notes for Maintainers

- Use this file as the source of truth for endpoint contracts.
- Re-export OpenAPI spec from `/openapi.json` for generated clients if needed.
- Keep frontend enum values synchronized with section 6.
- If backend contracts change, bump API docs and notify frontend team in the same PR.
