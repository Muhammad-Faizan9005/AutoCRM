# AutoCRM Backend - Authentication

## Overview

Authentication is JWT-based, delivered through **HttpOnly cookies** with a
double-submit CSRF guard. Cookies are the only transport for user auth:
`get_current_user` reads the `access_token` cookie and has no
`Authorization: Bearer` fallback, so a bearer header alone returns
`401 Not authenticated`. Tests and tooling must send the cookie.

The AI service authenticates separately with `X-AI-Service-Token` (see
[docs/API.md](docs/API.md) section 3.1), not with a bearer token.

---

## Components

### 1. Token + password utilities
**Location:** `app/auth/utils.py`

- Password hashing and verification with bcrypt (`passlib`)
- Access token creation (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, default 30 min)
- Refresh token creation (`JWT_REFRESH_TOKEN_EXPIRE_DAYS`, default 7 days)
- Token decoding/validation

### 2. Cookie + CSRF handling
**Location:** `app/auth/cookies.py`

| Cookie          | HttpOnly | Path        | Purpose                        |
| --------------- | -------- | ----------- | ------------------------------ |
| `access_token`  | yes      | `/`         | Authenticates API requests     |
| `refresh_token` | yes      | `/api/auth` | Rotates the access token       |
| `csrf_token`    | no       | `/`         | Read by JS for the CSRF header |

`csrf_middleware` requires the `X-CSRF-Token` header to match the `csrf_token`
cookie on every mutating request (`POST`, `PUT`, `PATCH`, `DELETE`) that carries
an auth cookie. `POST /api/auth/login` and `POST /api/auth/register` are exempt.

Cookies are marked `Secure` with `SameSite=None` when `DEBUG=False`, and
`SameSite=Lax` in local development.

### 3. Auth dependencies
**Location:** `app/auth/dependencies.py`

- `require_auth` — any authenticated, active user
- `require_admin`, `require_sales_manager_or_admin` — role gates
- `require_ai_agent_auth`, `require_human_or_ai_agent_auth` — AI service credentials
- Permission checks resolved via `PermissionService`

### 4. Token revocation
**Location:** `app/auth/token_store.py`

Logout and refresh rotation blacklist prior tokens in the `revoked_tokens`
table, so a stolen token stops working after logout.

---

## Endpoints

All under `/api/auth`:

| Method   | Endpoint           | Description                                  |
| -------- | ------------------ | -------------------------------------------- |
| `POST`   | `/register`        | Register an account, sets auth cookies (201) |
| `POST`   | `/login`           | Authenticate, sets auth cookies              |
| `GET`    | `/me`              | Current user profile + permissions           |
| `PATCH`  | `/profile`         | Update own profile                           |
| `POST`   | `/avatar`          | Upload avatar image                          |
| `DELETE` | `/avatar`          | Remove avatar                                |
| `POST`   | `/refresh`         | Rotate access/refresh pair                   |
| `POST`   | `/logout`          | Revoke tokens and clear cookies              |
| `POST`   | `/forgot-password` | Email a password reset link                  |
| `POST`   | `/reset-password`  | Consume reset token and set a new password   |

Allowed avatar types: JPEG, PNG, WebP, GIF. Avatars are stored locally and
served from the `/static/avatars` mount, or from Supabase S3 when configured.

---

## Database Setup

Apply migrations with Alembic — do not run ad-hoc DDL:

```bash
python -m alembic upgrade head
python -m alembic current
```

Relevant tables: `agents` (includes `password_hash`), `agent_permissions`,
`revoked_tokens`, and `password_reset_tokens`.

---

## Configuration

Set these in `.env` (see `.env.example`). Never commit real secrets.

```env
DEBUG=True
DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<db>?sslmode=require

JWT_SECRET_KEY=<min-32-char-random-secret>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

RESET_TOKEN_TTL_MINUTES=30
FRONTEND_BASE_URL=http://localhost:5173
```

Generate a strong secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Password reset emails require the Mailjet settings documented in `README.md`.

`app/core/startup_checks.py` validates configuration at boot: it aborts startup
on unsafe production values (`DEBUG=False`) and warns in development.

---

## Usage

### Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

### Cookie flow (browser clients)

```bash
# Login and persist cookies
curl -c cookies.txt -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"<password>"}'

# Authenticated GET
curl -b cookies.txt http://localhost:8000/api/auth/me

# Mutating request needs the CSRF header matching the csrf_token cookie
curl -b cookies.txt -X PATCH http://localhost:8000/api/auth/profile \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: <csrf_token cookie value>" \
  -d '{"full_name":"New Name"}'
```

### AI service flow (service-to-service)

```bash
curl http://localhost:8000/api/agent/leads/stale-candidates \
  -H "X-AI-Service-Token: <raw_token>" \
  -H "X-AI-Agent-Key: lead_nudge_agent"
```

Issue the token from Profile Settings -> Developer Mode -> AI Service
Credentials. Only its SHA-256 hash is stored; the raw value is shown once.

---

## Frontend Integration

The frontend must send cookies and the CSRF header; it must not store tokens in
`localStorage`.

```javascript
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api',
  withCredentials: true, // send/receive HttpOnly auth cookies
});

function readCookie(name) {
  return document.cookie
    .split('; ')
    .find((row) => row.startsWith(`${name}=`))
    ?.split('=')[1];
}

// Attach CSRF token on mutating requests
api.interceptors.request.use((config) => {
  if (['post', 'put', 'patch', 'delete'].includes(config.method)) {
    const csrf = readCookie('csrf_token');
    if (csrf) config.headers['X-CSRF-Token'] = csrf;
  }
  return config;
});

// Refresh once on 401, then retry
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config;
    if (error.response?.status === 401 && !config._retried) {
      config._retried = true;
      try {
        await api.post('/auth/refresh');
        return api(config);
      } catch {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);
```

CORS origins are allow-listed in `app/main.py`; add new frontend origins there,
since `allow_credentials=True` forbids wildcards.

For full endpoint contracts see `docs/API.md` and
`FRONTEND_INTEGRATION_GUIDE.md`.

Interactive docs while the server runs:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## Error Format

Errors are normalized by the global handler in `app/middleware/error_handler.py`:

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "request_id": "uuid",
    "timestamp": "2026-01-01T00:00:00Z"
  }
}
```

---

## Security Notes

Implemented:
- bcrypt password hashing
- HttpOnly, `Secure`, `SameSite` auth cookies
- CSRF double-submit validation on mutating requests
- Refresh-token rotation with revocation via `revoked_tokens`
- Role-based access control plus per-user permission overrides
- Rate limiting, security headers, request-size caps, and request IDs
- Row Level Security on sensitive tables

Production checklist:
- [ ] Set `DEBUG=False` so cookies become `Secure`
- [ ] Use a strong, unique `JWT_SECRET_KEY` from a secret manager
- [ ] Restrict CORS origins in `main.py` to real frontend domains
- [ ] Terminate TLS in front of the app
- [ ] Keep `RATE_LIMIT_ENABLED=true` and `SECURITY_HEADERS_ENABLED=true`
- [ ] Rotate database, Mailjet, and AI service credentials

---

## Troubleshooting

**403 "CSRF token missing or invalid"**
Send `X-CSRF-Token` matching the `csrf_token` cookie on mutating requests.

**401 "Invalid authentication credentials"**
Token expired, revoked after logout, malformed, or the user is inactive/deleted.
Call `POST /api/auth/refresh`.

**Cookies not stored by the browser**
Ensure the request uses `withCredentials: true`, the origin is allow-listed in
`main.py`, and HTTPS is used when `DEBUG=False`.

**Refresh returns 401 immediately**
The `refresh_token` cookie is scoped to `/api/auth`; refresh must be called on
that path.
