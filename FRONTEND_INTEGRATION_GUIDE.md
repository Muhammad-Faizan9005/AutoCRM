# Frontend Integration Guide: Connecting React to FastAPI Backend

**Backend URL:** `https://autocrmbackend-production-f017.up.railway.app`

## Architecture Overview

```
React Frontend → HTTP Requests → FastAPI Backend (Railway) → Supabase Database
                 ↓
         JWT Token in Headers
```

## Part 1: Understanding the API Structure

### Available Endpoints

Your FastAPI backend exposes these endpoint groups:

**Authentication (`/api/auth/`):**
- POST `/api/auth/register` - Create new user account
- POST `/api/auth/login` - Login and get tokens
- GET `/api/auth/me` - Get current user info (requires auth)
- POST `/api/auth/refresh` - Refresh access token
- POST `/api/auth/logout` - Logout (client-side token removal)

**Customers (`/api/customers/`):**
- GET `/api/customers` - List all customers (requires auth)
- POST `/api/customers` - Create customer (requires auth)
- GET `/api/customers/{id}` - Get customer details (requires auth)
- PUT `/api/customers/{id}` - Update customer (requires auth)
- DELETE `/api/customers/{id}` - Delete customer (requires auth)

**Tickets (`/api/tickets/`):**
- GET `/api/tickets` - List all tickets (requires auth)
- POST `/api/tickets` - Create ticket (requires auth)
- GET `/api/tickets/{id}` - Get ticket details (requires auth)
- PUT `/api/tickets/{id}` - Update ticket (requires auth)
- DELETE `/api/tickets/{id}` - Delete ticket (requires auth)
- GET `/api/tickets/customer/{customer_id}` - Get customer's tickets (requires auth)
- PATCH `/api/tickets/{id}/assign` - Assign ticket to agent (requires auth)

### API Documentation

Visit: `https://autocrmbackend-production-f017.up.railway.app/docs`

This interactive Swagger UI shows:
- All available endpoints
- Request/response formats
- Required fields
- Authentication requirements
- Try-it-out functionality for testing

## Part 3: Configuration Setup

### Step 1: Create API Configuration File

**Location:** `src/config/api.js`

**Purpose:** Central place to manage all API URLs

**What to include:**
- Backend base URL (your Railway URL)
- All endpoint paths
- Helper functions to construct URLs with parameters

### Step 2: Create Token Manager

**Location:** `src/utils/tokenManager.js`

**Purpose:** Handle token storage and retrieval

**Responsibilities:**
- Store access_token in localStorage
- Store refresh_token in localStorage
- Retrieve tokens when needed
- Clear tokens on logout
- Check if user is authenticated

**Storage Keys:**
- `access_token` - Short-lived token (30 minutes)
- `refresh_token` - Long-lived token (7 days)

### Step 3: Create API Client

**Location:** `src/utils/apiClient.js`

**Purpose:** Wrapper around fetch() that handles authentication

**Key features:**
- Automatically add `Authorization: Bearer {token}` header
- Automatically add `Content-Type: application/json` header
- Handle JSON parsing
- Handle errors
- Auto-refresh token on 401 responses
- Redirect to login on auth failure

## Part 4: Authentication Flow

### Registration Flow

1. **User Action:** Fill registration form (email, password, full_name, role)
2. **Frontend:** Send POST to `/api/auth/register`
3. **Request Body:** JSON with email, password, full_name, role
4. **Backend Response:** Returns access_token, refresh_token, user object
5. **Frontend:** Store both tokens in localStorage
6. **Frontend:** Redirect to dashboard

### Login Flow

1. **User Action:** Enter email and password
2. **Frontend:** Send POST to `/api/auth/login`
3. **Request Body:** JSON with email, password
4. **Backend Response:** Returns access_token, refresh_token, user object
5. **Frontend:** Store both tokens in localStorage
6. **Frontend:** Update global auth state
7. **Frontend:** Redirect to dashboard

### Token Refresh Flow

1. **Scenario:** API returns 401 Unauthorized
2. **Frontend:** Check if refresh_token exists
3. **Frontend:** Send POST to `/api/auth/refresh` with refresh_token
4. **Backend Response:** Returns new access_token
5. **Frontend:** Update access_token in localStorage
6. **Frontend:** Retry original request with new token
7. **If refresh fails:** Clear tokens and redirect to login

### Logout Flow

1. **User Action:** Click logout button
2. **Frontend:** Remove tokens from localStorage
3. **Frontend:** Clear global auth state
4. **Frontend:** Redirect to login page

## Part 5: Protected Routes

### Authentication Guard

**Purpose:** Prevent unauthorized access to protected pages

**Implementation Location:** `src/App.js` or routing component

**Logic:**
- Check if access_token exists in localStorage
- If authenticated: Render protected component
- If not authenticated: Redirect to login page

**Pages that need protection:**
- Dashboard
- Customer list/create/edit
- Ticket list/create/edit
- User profile

## Part 6: Making API Requests

### Pattern for All API Calls

1. **Import API client** from utils
2. **Get endpoint URL** from config
3. **Call API client** with method and data
4. **Handle loading state** (show spinner)
5. **Handle success** (update UI, show success message)
6. **Handle errors** (show error message)

### Example: Fetching Customers

**When:** Component mounts or user refreshes
**Endpoint:** GET `/api/customers`
**Authentication:** Required (automatic via API client)
**Response:** Array of customer objects
**UI Update:** Populate customer list component

### Example: Creating a Customer

**When:** User submits customer form
**Endpoint:** POST `/api/customers`
**Request Body:** JSON with name, email, phone, company
**Authentication:** Required (automatic)
**Response:** Created customer object with ID
**UI Update:** Add to list, show success message, close form

### Example: Creating a Ticket

**When:** User submits ticket form
**Endpoint:** POST `/api/tickets`
**Request Body:** JSON with title, description, customer_id, priority, status
**Authentication:** Required
**Response:** Created ticket object with ID
**UI Update:** Add to list, show success message, redirect to ticket details

## Part 7: Service Layer Pattern

### Authentication Service (`src/services/authService.js`)

**Functions to create:**
- `register(email, password, fullName, role)` - User registration
- `login(email, password)` - User login
- `logout()` - Clear tokens and logout
- `getCurrentUser()` - Get logged-in user info
- `refreshAccessToken(refreshToken)` - Refresh token
- `isAuthenticated()` - Check if user is logged in

### Customer Service (`src/services/customerService.js`)

**Functions to create:**
- `getAllCustomers()` - Fetch all customers
- `getCustomerById(id)` - Fetch single customer
- `createCustomer(customerData)` - Create new customer
- `updateCustomer(id, customerData)` - Update customer
- `deleteCustomer(id)` - Delete customer

### Ticket Service (`src/services/ticketService.js`)

**Functions to create:**
- `getAllTickets()` - Fetch all tickets
- `getTicketById(id)` - Fetch single ticket
- `getCustomerTickets(customerId)` - Fetch customer's tickets
- `createTicket(ticketData)` - Create new ticket
- `updateTicket(id, ticketData)` - Update ticket
- `assignTicket(id, agentId)` - Assign ticket to agent
- `deleteTicket(id)` - Delete ticket

## Part 8: State Management

### Option A: Context API (Recommended for simpler apps)

**Create:** `src/context/AuthContext.js`

**Provides:**
- Current user object
- Loading state
- Login function
- Logout function
- Register function

**Wrap:** Your App.js with AuthProvider

### Option B: Redux (For complex state)

**Store slices needed:**
- Auth slice (user, tokens, loading)
- Customers slice (list, current, loading)
- Tickets slice (list, current, loading)

## Part 9: Error Handling Strategy

### Error Types to Handle

1. **Network Errors:** Backend unreachable
2. **Authentication Errors:** 401 (token expired/invalid)
3. **Authorization Errors:** 403 (insufficient permissions)
4. **Validation Errors:** 400 (invalid input)
5. **Not Found Errors:** 404 (resource doesn't exist)
6. **Server Errors:** 500 (backend error)

### Where to Handle Errors

- **API Client:** Network and auth errors (401 auto-refresh)
- **Service Layer:** Parse error messages
- **Components:** Display error messages to user

### User Feedback

- Show toast/snackbar for success/error messages
- Display inline errors on form fields
- Show loading spinners during requests
- Disable buttons during submission

## Part 10: Development Workflow

### Step-by-Step Implementation

**Phase 1: Setup Foundation**
1. Create config/api.js with Railway URL
2. Create utils/tokenManager.js for token storage
3. Create utils/apiClient.js for fetch wrapper
4. Test API connectivity (check /docs endpoint)

**Phase 2: Authentication**
1. Create services/authService.js
2. Create AuthContext for global state
3. Build Login component
4. Build Register component
5. Test registration → login → token storage

**Phase 3: Protected Routes**
1. Create PrivateRoute component
2. Wrap dashboard and other pages
3. Test redirect to login when not authenticated

**Phase 4: Customer Features**
1. Create services/customerService.js
2. Build CustomerList component (fetch and display)
3. Build CustomerForm component (create/edit)
4. Test CRUD operations

**Phase 5: Ticket Features**
1. Create services/ticketService.js
2. Build TicketList component
3. Build TicketForm component
4. Test CRUD operations

**Phase 6: Polish**
1. Add loading states
2. Add error handling
3. Add success messages
4. Add form validation

## Part 11: Testing the Integration

### Manual Testing Checklist

**Authentication Tests:**
- [ ] Register new account
- [ ] Login with created account
- [ ] Access protected page (should work)
- [ ] Logout and try accessing protected page (should redirect)
- [ ] Login with wrong password (should show error)
- [ ] Token expires (wait 30min or modify expiry) - should auto-refresh
- [ ] Refresh token expires (should redirect to login)

**Customer Tests:**
- [ ] View customer list
- [ ] Create new customer
- [ ] Edit existing customer
- [ ] Delete customer
- [ ] View customer details

**Ticket Tests:**
- [ ] View ticket list
- [ ] Create new ticket
- [ ] Assign ticket to customer
- [ ] Update ticket status
- [ ] Delete ticket

### Using Browser DevTools

1. **Network Tab:**
   - Monitor API requests
   - Check request headers (Authorization present?)
   - Check response status codes
   - View response data

2. **Application Tab:**
   - Check localStorage for tokens
   - Verify tokens are stored correctly
   - Clear tokens to test logout

3. **Console Tab:**
   - Check for API errors
   - View fetch request logs
   - Debug authentication issues

## Part 12: Common Issues and Solutions

### Issue: CORS Errors

**Symptom:** Browser blocks requests with CORS policy error

**Solution:** Your backend already has CORS configured. If you still see errors:
- Check backend is running
- Verify you're using correct URL (https)
- Check browser console for exact error

### Issue: 401 Unauthorized

**Symptom:** All API requests return 401

**Possible causes:**
- Token not being sent (check Authorization header)
- Token expired (implement refresh logic)
- Token format wrong (must be "Bearer {token}")
- User not logged in (redirect to login)

### Issue: Token Not Persisting

**Symptom:** User logged out on page refresh

**Solution:**
- Ensure tokens saved to localStorage (not state only)
- Check token retrieval on app load
- Initialize auth state from localStorage on mount

### Issue: Can't Access User Data

**Symptom:** API returns empty or wrong data

**Possible causes:**
- Wrong endpoint URL
- Missing authentication
- User doesn't have permission
- Data doesn't exist in database

## Part 13: Environment Variables

### Create `.env` file in React project root

**Required variables:**
```
REACT_APP_API_BASE_URL=https://autocrmbackend-production-f017.up.railway.app
```

### Usage in code

Access via: `process.env.REACT_APP_API_BASE_URL`

**Benefits:**
- Easy to change between dev/prod
- Keep sensitive data out of code
- Different URLs for different environments

## Part 14: Deployment Considerations

### Before Deploying Frontend

1. **Update API URL:** Use production Railway URL
2. **Test all features:** Ensure everything works with production backend
3. **Check CORS:** Backend allows your frontend domain
4. **Build optimized:** Run production build
5. **Configure hosting:** Vercel/Netlify/Railway for frontend

### CORS Configuration

Your backend needs to allow requests from your frontend domain.

**Current setup:** Allows all origins (`*`)

**Production setup:** Should specify exact frontend URL in backend's CORS middleware

**To update backend CORS:** Modify `app/main.py` to include your frontend URL in allowed origins

## Part 15: Quick Start Summary

### For React Developer Starting from Scratch:

1. **Get familiar with API:**
   - Visit https://autocrmbackend-production-f017.up.railway.app/docs
   - Read all endpoints and their requirements
   - Test endpoints manually in Swagger UI

2. **Set up project structure:**
   - Create folders: config, services, utils, context
   - Create files for each service layer
   - Organize components by feature

3. **Build authentication first:**
   - This is the foundation
   - All other features depend on it
   - Test thoroughly before moving on

4. **Build features incrementally:**
   - Start with read operations (GET)
   - Then add create operations (POST)
   - Then update/delete (PUT/DELETE)
   - Test each before moving to next

5. **Add polish last:**
   - Loading states
   - Error messages
   - Form validation
   - Success notifications

### Key Principles:

- **One source of truth:** All API configuration in one file
- **Separation of concerns:** Services handle API, components handle UI
- **Reusability:** Create shared API client for all requests
- **Security:** Never expose tokens, always use HTTPS
- **User experience:** Show loading states and clear error messages

## Part 16: API Request/Response Examples

### Registration Response Format:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "full_name": "John Doe",
    "role": "agent",
    "is_active": true
  }
}
```

### Customer Object Format:
```json
{
  "id": 1,
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "+1234567890",
  "company": "ABC Corp",
  "created_at": "2026-03-08T10:30:00",
  "updated_at": "2026-03-08T10:30:00"
}
```

### Ticket Object Format:
```json
{
  "id": 1,
  "title": "Login Issue",
  "description": "Cannot login to account",
  "status": "open",
  "priority": "high",
  "customer_id": 1,
  "assigned_to": 2,
  "created_at": "2026-03-08T10:30:00",
  "updated_at": "2026-03-08T10:30:00"
}
```

### Error Response Format:
```json
{
  "detail": "Invalid credentials"
}
```

---

## Next Steps

1. ✅ Backend deployed to Railway
2. ⏭️ Set up React project structure
3. ⏭️ Configure API base URL
4. ⏭️ Implement authentication
5. ⏭️ Build customer management
6. ⏭️ Build ticket management
7. ⏭️ Deploy frontend

**Need help?** 
- Check backend API docs: https://autocrmbackend-production-f017.up.railway.app/docs
- Test endpoints in Swagger UI before coding
- Start simple and add complexity gradually
