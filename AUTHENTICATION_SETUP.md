# AutoCRM Backend - Authentication Implementation

## ✅ What Was Implemented

I've successfully implemented **minimal required functionalities** for the backend to connect with the frontend and have basic functionality:

### 1. **JWT Authentication System** ✓
- **Location:** `app/auth/`
- **Files Created:**
  - `utils.py` - Password hashing (bcrypt) and JWT token generation/validation
  - `dependencies.py` - Authentication middleware for protecting endpoints
  
**Features:**
- Secure password hashing with bcrypt
- JWT access tokens (30 min expiry)
- JWT refresh tokens (7 days expiry)
- Token verification and validation
- Current user extraction from tokens

### 2. **Authentication Endpoints** ✓
- **Location:** `app/routers/auth.py`

**Available Endpoints:**
- `POST /api/auth/register` - Register new agent/user
- `POST /api/auth/login` - Login and get tokens
- `GET /api/auth/me` - Get current user profile
- `POST /api/auth/refresh` - Refresh access token
- `POST /api/auth/logout` - Logout (token invalidation)

### 3. **Authentication Schemas** ✓
- **Location:** `app/schemas/auth.py`

**Schemas:**
- `LoginRequest` - Email & password
- `RegisterRequest` - Email, password, full name, role
- `LoginResponse` - Tokens + user data
- `TokenResponse` - Access & refresh tokens
- `UserResponse` - User profile data

### 4. **Error Handling System** ✓
- **Location:** `app/exceptions/` and `app/middleware/`

**Features:**
- Custom exception classes (Authentication, Authorization, NotFound, Validation, Database, ExternalService)
- Global error handler middleware
- Standardized error response format:
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "request_id": "uuid",
    "timestamp": "2026-03-08T..."
  }
}
```

### 5. **Protected Endpoints** ✓
All existing customer and ticket endpoints now require authentication:

**Customers:** `/api/customers/`
- GET `/` - List customers (authenticated)
- GET `/{id}` - Get customer (authenticated)
- POST `/` - Create customer (authenticated)
- PATCH `/{id}` - Update customer (authenticated)
- DELETE `/{id}` - Delete customer (authenticated)

**Tickets:** `/api/tickets/`
- GET `/` - List tickets (authenticated)
- GET `/{id}` - Get ticket (authenticated)
- POST `/` - Create ticket (authenticated)
- PATCH `/{id}` - Update ticket (authenticated)
- DELETE `/{id}` - Delete ticket (authenticated)
- GET `/{id}/messages` - Get messages (authenticated)
- POST `/{id}/messages` - Create message (authenticated)

---

## 🗄️ Database Setup

### Required: Add password_hash Column

The agents table needs a `password_hash` column. Run this migration:

**Option 1: Run the migration file**
```sql
-- Located at: database/migrations/001_add_password_to_agents.sql
-- Execute this in your Supabase SQL editor
```

**Option 2: Run directly in Supabase**
```sql
ALTER TABLE agents ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255) NOT NULL;
```

---

## ⚙️ Configuration

### Environment Variables (.env)
Updated configuration with JWT settings:

```env
# Application Settings
APP_NAME=AutoCRM
DEBUG=True

# Supabase Settings
SUPABASE_URL=https://snwheczzakjyhfaitmoq.supabase.co
SUPABASE_KEY=sb_secret_B-SlQkUTBf7hcxGWBUIYNw_gqKbjbcN

# JWT Settings
jwt_secret_key=your-super-secret-key-change-this-to-something-random-and-secure-minimum-32-characters
jwt_algorithm=HS256
jwt_access_token_expire_minutes=30
jwt_refresh_token_expire_days=7
```

**⚠️ Important:** Change the `jwt_secret_key` to a secure random string before production!

Generate a secure key:
```bash
# Python
python -c "import secrets; print(secrets.token_urlsafe(32))"

# OpenSSL
openssl rand -base64 32
```

---

## 🚀 How to Use

### 1. **Start the Server**
```bash
cd backend
uvicorn app.main:app --reload
```

### 2. **Register a New User**
```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@autocrm.com",
    "password": "SecurePass123!",
    "full_name": "Admin User",
    "role": "admin"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "email": "admin@autocrm.com",
    "full_name": "Admin User",
    "role": "admin",
    "is_active": true,
    "created_at": "2026-03-08T..."
  }
}
```

### 3. **Login**
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@autocrm.com",
    "password": "SecurePass123!"
  }'
```

### 4. **Access Protected Endpoints**
Use the `access_token` in the Authorization header:

```bash
curl -X GET http://localhost:8000/api/customers/ \
  -H "Authorization: Bearer eyJhbGc..."
```

### 5. **Get Current User**
```bash
curl -X GET http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer eyJhbGc..."
```

### 6. **Refresh Token**
```bash
curl -X POST http://localhost:8000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJhbGc..."
  }'
```

---

## 🌐 Frontend Integration

### Axios Example (React/Vue/Angular)

```javascript
import axios from 'axios';

// Create axios instance
const api = axios.create({
  baseURL: 'http://localhost:8000/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle token refresh on 401
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      const refreshToken = localStorage.getItem('refresh_token');
      if (refreshToken) {
        try {
          const { data } = await axios.post('/api/auth/refresh', {
            refresh_token: refreshToken,
          });
          localStorage.setItem('access_token', data.access_token);
          localStorage.setItem('refresh_token', data.refresh_token);
          
          // Retry original request
          error.config.headers.Authorization = `Bearer ${data.access_token}`;
          return axios(error.config);
        } catch (refreshError) {
          // Refresh failed, redirect to login
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          window.location.href = '/login';
        }
      }
    }
    return Promise.reject(error);
  }
);

// Usage examples
export const authService = {
  async login(email, password) {
    const { data } = await api.post('/auth/login', { email, password });
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return data;
  },

  async register(email, password, full_name) {
    const { data } = await api.post('/auth/register', {
      email,
      password,
      full_name,
      role: 'agent',
    });
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return data;
  },

  async getCurrentUser() {
    const { data } = await api.get('/auth/me');
    return data;
  },

  logout() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    window.location.href = '/login';
  },
};

export const customerService = {
  async getCustomers() {
    const { data } = await api.get('/customers/');
    return data;
  },

  async createCustomer(customerData) {
    const { data } = await api.post('/customers/', customerData);
    return data;
  },
};

export const ticketService = {
  async getTickets() {
    const { data } = await api.get('/tickets/');
    return data;
  },

  async createTicket(ticketData) {
    const { data } = await api.post('/tickets/', ticketData);
    return data;
  },
};
```

---

## 📝 API Documentation

Once the server is running, access interactive API docs at:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## 🔒 Security Notes

### Current Implementation
✅ Password hashing with bcrypt
✅ JWT tokens with expiration
✅ Bearer token authentication
✅ HTTPS-ready (configure in production)
✅ Error handling doesn't leak sensitive info

### Production Checklist
- [ ] Change `jwt_secret_key` to a strong random value
- [ ] Update CORS origins in `main.py` to specific domains
- [ ] Use HTTPS in production
- [ ] Consider rate limiting on auth endpoints
- [ ] Set up proper logging and monitoring
- [ ] Use environment-specific secrets management

---

## 🐛 Troubleshooting

### "Invalid authentication credentials"
- Token expired (get new token via refresh endpoint)
- Token malformed (check Bearer prefix)
- User not found or inactive

### "Incorrect email or password"
- Check credentials
- Ensure user is registered

### "Column 'password_hash' does not exist"
- Run the database migration (see Database Setup section)

### CORS Issues
- Backend allows all origins by default
- Update `allow_origins` in `main.py` if needed

---

## ✨ What's Next (Optional Enhancements)

The current implementation provides **minimal viable authentication**. Future improvements from the development plan:

- **Role-Based Access Control (RBAC)** - Different permissions per role
- **Repository Pattern** - Better database abstraction
- **Input Validation** - XSS/SQL injection prevention
- **Rate Limiting** - Prevent brute force attacks
- **Logging System** - Structured JSON logging
- **Testing** - Unit and integration tests
- **AI Features** - Ticket categorization, sentiment analysis

---

## 📁 File Structure

```
backend/
├── app/
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── utils.py              # JWT & password utilities
│   │   └── dependencies.py       # Auth middleware
│   ├── exceptions/
│   │   ├── __init__.py
│   │   └── custom_exceptions.py  # Custom error classes
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── error_handler.py      # Global error handler
│   ├── routers/
│   │   ├── auth.py              # Auth endpoints (NEW)
│   │   ├── customers.py         # Protected with auth
│   │   └── tickets.py           # Protected with auth
│   ├── schemas/
│   │   └── auth.py              # Auth request/response models
│   ├── config.py                # Updated with JWT settings
│   └── main.py                  # Updated with auth router
├── database/
│   ├── schema.sql               # Updated with password_hash
│   └── migrations/
│       └── 001_add_password_to_agents.sql
└── .env                         # Updated with JWT config
```

---

## 🎉 Summary

You now have a **fully functional authenticated backend** that can:
1. ✅ Register and login users
2. ✅ Issue and validate JWT tokens
3. ✅ Protect all customer and ticket endpoints
4. ✅ Handle errors gracefully
5. ✅ Refresh expired tokens
6. ✅ Ready for frontend integration

The backend is ready to connect with your frontend application! 🚀
