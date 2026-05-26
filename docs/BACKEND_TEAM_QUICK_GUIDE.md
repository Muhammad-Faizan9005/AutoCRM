# AutoCRM Backend Quick Guide

## 2) What This Backend Does

- Provides CRM APIs for auth, users, customers, tickets, ticket messages, and file imports.
- Uses PostgreSQL via a custom query client.
- Uses JWT authentication with access + refresh tokens.
- Applies role-based access control (admin, sales_manager, sales_rep).
- Adds production-focused middleware (security headers, request size guard, rate limiting, request ID, logging, error format).

## 3) Fundamentals (simple definitions)

### FastAPI

- A Python web framework for building APIs quickly.
- Gives routing, dependency injection, request validation, and OpenAPI docs out of the box.
- In this project, FastAPI app startup is in `app/main.py`.

### REST API

- A style of API where resources are exposed via URLs and HTTP methods.
- Example in this backend:
  - `GET /api/customers/` -> list customers
  - `POST /api/tickets/` -> create ticket

### JWT (JSON Web Token)

- A signed token used for stateless authentication.
- Backend verifies signature and claims on every protected request.
- This project uses:
  - Access token (short-lived)
  - Refresh token (longer-lived)

### Access Token vs Refresh Token

- Access token: sent on protected API calls in `Authorization: Bearer <token>`.
- Refresh token: used only to ask for a new token pair when access token expires.
- This backend rotates refresh tokens and revokes old ones.

### RBAC (Role-Based Access Control)

- Authorization based on user role.
- Roles here: `admin`, `sales_manager`, `sales_rep`.
- Example: deleting users/customers/tickets requires admin-level permission.

### Middleware

- Code that runs around each request/response.
- This backend middleware handles:
  - request ID
  - logs
  - rate limiting
  - security headers + request size limit

### Dependency Injection (DI)

- FastAPI pattern to inject shared logic (auth checks, DB client) into endpoints.
- In this project, `Depends(...)` is used for auth and repository creation.

### Pydantic Schemas

- Typed models for validating request/response data.
- Prevents invalid payloads and enforces field constraints.

### Repository Pattern

- Data access is isolated in repository classes.
- Routers stay focused on API behavior; repositories handle DB operations.

### CORS

- Controls which frontend origins can call this API from browsers.
- Currently open (`allow_origins=["*"]`) and should be restricted in production.

### RLS (Row-Level Security)

- Database-level access policies in PostgreSQL/Supabase.
- Schema enables RLS for core tables; policy behavior depends on DB role/JWT context.

## 4) Project Flow In One View

```text
Client
  -> FastAPI app (app/main.py)
  -> Middleware chain (security, rate limit, logging, error handler)
  -> Router endpoint (app/routers/*)
  -> Auth dependency (if protected)
  -> Pydantic schema validation (app/schemas/*)
  -> Repository (app/repositories/*)
  -> Postgres client/query builder
  -> PostgreSQL tables
  -> JSON response (+ X-Request-ID, rate-limit headers)
```

## 5) Request Lifecycle (protected endpoint example)

Example: `GET /api/customers/`

1. Request enters FastAPI app.
2. Middleware runs:
   - security checks request size and adds headers
   - rate limiter checks per-IP and per-path budget
   - logging writes start/completion logs
   - error middleware ensures `X-Request-ID`
3. Auth dependency validates bearer token:
   - checks token blacklist (revoked tokens)
   - verifies JWT signature + claims
   - loads current user from `agents` table
4. Router validates query params and calls repository.
5. Repository executes DB query through the query client.
6. Response is returned in a consistent JSON shape.

## 6) Auth Flow In This Codebase

- `POST /api/auth/register`
  - creates a new `sales_rep` user
  - hashes password
  - returns access + refresh token

- `POST /api/auth/login`
  - verifies email/password
  - returns access + refresh token

- `GET /api/auth/me`
  - reads current user from bearer token

- `POST /api/auth/refresh`
  - validates refresh token
  - issues new token pair
  - blacklists old refresh token (rotation)

- `POST /api/auth/logout`
  - blacklists access token and optional refresh token

## 7) Core Data Model (what to memorize)

- `agents`: backend users, roles, password hash, active flag
- `revoked_tokens`: invalidated JWT token hashes
- `customers`: CRM customer profiles
- `tickets`: support/service records linked to customers
- `ticket_messages`: conversation thread per ticket
- `ai_interactions`: placeholder/log table for AI-related operations

Relationship summary:

- one customer -> many tickets
- one ticket -> many ticket messages
- one agent can be assigned to many tickets

## 8) Endpoint Cheat Sheet (most used)

- Auth:
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `GET /api/auth/me`
  - `POST /api/auth/refresh`
  - `POST /api/auth/logout`

- Users (admin-focused):
  - `GET /api/users/`
  - `POST /api/users/`
  - `PATCH /api/users/{user_id}`

- Customers:
  - `GET /api/customers/`
  - `POST /api/customers/`
  - `PATCH /api/customers/{customer_id}`

- Tickets:
  - `GET /api/tickets/`
  - `POST /api/tickets/`
  - `GET /api/tickets/{ticket_id}/messages`
  - `POST /api/tickets/{ticket_id}/messages`

- Imports:
  - `POST /api/import/customers`
  - `POST /api/import/tickets`

## 9) 3-Minute Demo Script

- Start backend and open `/docs`.
- Call `POST /api/auth/login` and copy access token.
- Authorize in Swagger with `Bearer <token>`.
- Call `GET /api/customers/` and `GET /api/tickets/`.
- Explain where auth, validation, and repository logic are applied.

## 10) Quick Glossary (backend terms)

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

## 11) Disabled User Detection (frontend behavior)

We need disabled users to lose access quickly. These are the options:

1) Server-push (SSE or WebSocket)
  - Backend publishes a "user_disabled" event to the specific user.
  - Frontend reacts instantly and clears the session.
  - Best long-term scalability, requires persistent connections and auth on the channel.

2) Short-interval polling (current)
  - Frontend polls `GET /api/auth/me` every ~6 seconds while logged in.
  - If the backend returns `403 Inactive user`, the client clears the session
    and shows the inactive modal.
  - Simple and reliable; load scales with concurrent active users.

3) Token revocation + short-lived access tokens
  - Disable action blacklists active tokens and uses shorter access token TTLs.
  - User is blocked on the next API request, without polling.
  - Lowest steady-state load, but not instant unless requests are frequent.
- Middleware: pre/post request processing layer.
- Dependency: reusable logic injected into route handlers.
- Repository: abstraction over DB operations.
- RLS: DB-level per-row access policy.

## 11) What Team Members Should Know After 20 Minutes

- Where requests enter and how they move through the backend.
- How JWT auth and refresh-token rotation work in this project.
- Where role checks are enforced.
- Where to add new endpoints, schemas, and repository logic safely.
- Which tables are core for day-to-day CRM operations.
