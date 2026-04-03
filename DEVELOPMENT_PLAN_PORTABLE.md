# AutoCRM Backend - 2-Week Development Plan
## Production-Grade Foundational Backend (Portable, No Frappe Runtime)

**Project Duration:** 2 Weeks (14 Days)
**Start Date:** March 24, 2026
**Target Completion:** April 7, 2026
**Methodology:** Agile Development with Daily Progress Tracking

---

## Executive Summary

This plan outlines the development of a production-grade foundational backend for AutoCRM as a standalone FastAPI system. The focus is on building a secure, scalable, AI-ready backend while avoiding Frappe Bench and any runtime dependency on Frappe framework internals.

### Current State Assessment

**Existing Infrastructure:**
- FastAPI-oriented planning and desired architecture are already defined.
- PostgreSQL/Supabase direction is clear.
- Core CRM features are already modeled in this codebase (as Frappe app logic).
- Telephony and communication flows exist conceptually and can be ported.

**What Needs to Be Built:**
- Standalone authentication and authorization system (JWT + RBAC)
- Non-Frappe data models and repository layer
- Ported CRM business logic into pure domain services
- AI/LLM service layer with provider abstraction
- Message and conversation timeline system
- Meeting intelligence pipeline (transcript, summary, action items)
- Production-grade error handling, logging, and security hardening
- Comprehensive testing suite
- Dockerized deployment and complete API documentation

---

## Project Goals

### Primary Objectives
1. **Security First:** Implement robust authentication, authorization, and input validation
2. **Portable Architecture:** Build backend with no Frappe runtime coupling
3. **AI-Ready Services:** Add scalable LLM integration for core CRM workflows
4. **Production Standards:** Error handling, logging, monitoring, and performance optimization
5. **Developer Experience:** Clear docs, predictable setup, maintainable architecture

### Success Metrics
- All endpoints run without `frappe` imports
- 3+ AI features operational (lead scoring, summary, response suggestions)
- API response times < 250ms (95th percentile, non-AI endpoints)
- 70%+ test coverage
- Zero critical security vulnerabilities
- Docker deployment ready

---

## WEEK 1: Core Infrastructure and Porting Foundation

### **Day 1: Monday - Authentication Foundation**
**Goal:** Implement complete JWT-based authentication system

#### Morning (4 hours)
**Task 1.1: JWT Authentication Core**
- Create `app/auth/utils.py`
  - Password hashing with bcrypt
  - JWT token generation and validation
  - Token expiry handling
  - Refresh token mechanism
- Create `app/auth/dependencies.py`
  - `get_current_user` dependency
  - `require_auth` dependency
  - Token extraction from headers

**Files to Create:**
```
app/auth/
|-- __init__.py
|-- utils.py
`-- dependencies.py
```

#### Afternoon (4 hours)
**Task 1.2: Authentication Endpoints**
- Create `app/routers/auth.py`
  - POST `/auth/register`
  - POST `/auth/login`
  - POST `/auth/refresh`
  - POST `/auth/logout`
  - GET `/auth/me`
- Create `app/schemas/auth.py`
  - `LoginRequest`, `LoginResponse`
  - `RegisterRequest`, `RegisterResponse`
  - `TokenResponse`, `RefreshTokenRequest`

**Testing:**
- Register, login, refresh flow
- Access protected routes
- Verify invalid token responses

**Deliverables:**
- Working JWT authentication
- 5 authentication endpoints
- Password security with bcrypt
- Token-based session management

---

### **Day 2: Tuesday - Role-Based Access Control (RBAC)**
**Goal:** Implement complete authorization system with roles

#### Morning (4 hours)
**Task 2.1: User and Agent Management**
- Create `app/routers/users.py`
  - GET `/users`
  - GET `/users/{id}`
  - POST `/users`
  - PATCH `/users/{id}`
  - DELETE `/users/{id}`
- Create `app/schemas/user.py`
  - `UserBase`, `UserCreate`, `UserUpdate`, `UserResponse`
  - roles: `admin`, `sales_manager`, `sales_rep`

#### Afternoon (4 hours)
**Task 2.2: Permission System**
- Update `app/auth/dependencies.py`
  - `require_role(allowed_roles: list[str])`
  - `require_admin()`
  - `require_sales_manager_or_admin()`
- Define permission matrix equivalent to CRM workflows

**Testing:**
- Role-level access tests
- Unauthorized access returns 403
- Admin-only operations

**Deliverables:**
- Complete user/agent CRUD
- Role-based permissions
- Security middleware in place

---

### **Day 3: Wednesday - Database Layer and Migration Base**
**Goal:** Implement repository pattern and PostgreSQL-ready schema

#### Morning (4 hours)
**Task 3.1: Repository Pattern Implementation**
- Create `app/repositories/base.py`
  - Generic CRUD operations
  - Transaction handling
  - Error mapping
- Create repositories:
  - `customer_repository.py`
  - `lead_repository.py`
  - `deal_repository.py`
  - `task_repository.py`
  - `message_repository.py`

#### Afternoon (4 hours)
**Task 3.2: SQLAlchemy + Alembic Setup**
- Create `app/db/session.py`
- Create initial Alembic migration
- Create `database/seeds/dev_data.sql`
  - users, leads, deals, tasks, messages

**Testing:**
- Repository CRUD
- Migration up/down
- Seed loading

**Deliverables:**
- Repository layer operational
- Alembic migration baseline
- Development seed data

---

### **Day 4: Thursday - Error Handling and Logging**
**Goal:** Implement production-grade error handling and structured logging

#### Morning (4 hours)
**Task 4.1: Exception Handling System**
- Create `app/exceptions/custom_exceptions.py`
  - `AuthenticationError`
  - `AuthorizationError`
  - `ResourceNotFoundError`
  - `ValidationError`
  - `DatabaseError`
  - `ExternalServiceError`
- Create `app/middleware/error_handler.py`

#### Afternoon (4 hours)
**Task 4.2: Structured Logging**
- Create `app/utils/logger.py`
- Create `app/middleware/logging_middleware.py`
- Add request correlation ID support

**Testing:**
- Trigger controlled errors
- Verify response format
- Verify JSON log shape

**Deliverables:**
- Global error handler
- Structured JSON logging
- Request/response logging

---

### **Day 5: Friday - Security Hardening**
**Goal:** Add rate limiting, sanitization, and secure defaults

#### Morning (4 hours)
**Task 5.1: Input Validation and Sanitization**
- Create `app/validators/custom_validators.py`
- Create `app/utils/sanitization.py`
- Add strict schema validation and length limits

#### Afternoon (4 hours)
**Task 5.2: Security Middleware**
- Create `app/middleware/rate_limiter.py`
- Create `app/middleware/security.py`
- Add security headers and request size limits

**Testing:**
- Rate-limit tests
- Validation tests
- injection/XSS payload tests

**Deliverables:**
- Input validation system
- Rate limiting middleware
- Security headers and sanitization

---

### **Day 6-7: Weekend - Week 1 Testing and Docs**
**Goal:** Consolidate week 1 and validate baseline quality

#### Saturday
**Task 6.1: Integration Testing**
- Test auth flow
- Test RBAC behavior
- Test error handling and rate limiting
- Test migration and repositories

**Task 6.2: Code Quality**
- Run `black`, `ruff`/`flake8`, `mypy`
- Fix lint and typing issues

#### Sunday
**Task 7.1: Documentation**
- Update README setup section
- Document auth and RBAC contracts
- Add environment variable reference

**Week 1 Review Checklist:**
- Auth endpoints verified
- RBAC verified
- Repository pattern in place
- Error handling and logs verified
- Security middleware verified
- Code quality checks passed

---

## WEEK 2: CRM Porting + AI Features + Release Readiness

### **Day 8: Monday - CRM Domain Porting (Lead/Deal/Task)**
**Goal:** Port core CRM logic from codebase into standalone services

#### Morning (4 hours)
**Task 8.1: Lead and Deal Domain Services**
- Create `app/services/lead_service.py`
- Create `app/services/deal_service.py`
- Port logic from:
  - `crm/crm/fcrm/doctype/crm_lead/crm_lead.py`
  - `crm/crm/fcrm/doctype/crm_deal/crm_deal.py`

#### Afternoon (4 hours)
**Task 8.2: Task and Assignment Services**
- Create `app/services/task_service.py`
- Port assignment behavior from:
  - `crm/crm/fcrm/doctype/crm_task/crm_task.py`

**Testing:**
- Lead lifecycle tests
- Deal status transition tests
- Assignment tests

**Deliverables:**
- Lead/deal/task services working
- Core business rules ported

---

### **Day 9: Tuesday - Communication and Activity Timeline**
**Goal:** Build unified communication + activity services

#### Morning (4 hours)
**Task 9.1: Timeline Aggregation Service**
- Create `app/services/activity_service.py`
- Port aggregation concepts from:
  - `crm/crm/api/activities.py`

#### Afternoon (4 hours)
**Task 9.2: Comments and Notifications**
- Create `app/services/notification_service.py`
- Create `app/routers/notifications.py`
- Port mention/notification concepts from:
  - `crm/crm/api/comment.py`
  - `crm/crm/fcrm/doctype/crm_notification/crm_notification.py`
  - `crm/crm/api/notifications.py`

**Testing:**
- Timeline ordering tests
- Mention notification tests
- Read/unread tests

**Deliverables:**
- Unified timeline endpoint
- Notification center operational

---

### **Day 10: Wednesday - Calls and Meeting Pipeline**
**Goal:** Build call logs and meeting intelligence ingestion base

#### Morning (4 hours)
**Task 10.1: Call Logging and Telephony Webhooks**
- Create `app/routers/telephony.py`
- Create `app/services/call_service.py`
- Port webhook and mapping logic from:
  - `crm/crm/integrations/twilio/api.py`
  - `crm/crm/integrations/exotel/handler.py`
  - `crm/crm/fcrm/doctype/crm_call_log/crm_call_log.py`

#### Afternoon (4 hours)
**Task 10.2: Recording Processing Hooks**
- Create `app/workers/recording_jobs.py`
- Add placeholder STT adapter interface
- Persist transcript and action-item placeholders

**Testing:**
- Webhook contract tests
- Call status mapping tests
- recording pipeline tests

**Deliverables:**
- Call APIs and webhook handlers
- Transcript pipeline skeleton

---

### **Day 11: Thursday - AI Service Layer**
**Goal:** Build provider abstraction and core AI workflows

#### Morning (4 hours)
**Task 11.1: LLM Service Interface**
- Create `app/services/llm/base_llm_service.py`
- Create provider adapters:
  - `openai_service.py`
  - `ollama_service.py`
- Create `factory.py`

#### Afternoon (4 hours)
**Task 11.2: AI CRM Services**
- Create `app/services/ai_lead_service.py`
- Create `app/services/ai_message_service.py`
- Create `app/services/ai_meeting_service.py`
- Create `app/schemas/ai.py`

**Testing:**
- Provider failover tests
- AI response schema validation
- latency and timeout tests

**Deliverables:**
- LLM provider abstraction
- 3 AI workflow services

---

### **Day 12: Friday - API Integration and Workflow Tests**
**Goal:** Integrate all modules and stabilize API behavior

#### Morning (4 hours)
**Task 12.1: API Integration Tests**
- Auth + RBAC + CRM CRUD
- Timeline and notification endpoints
- Telephony webhook endpoints
- AI endpoint contracts

#### Afternoon (4 hours)
**Task 12.2: Edge Cases and Failure Handling**
- Invalid payloads
- timeout/fallback behavior
- permission denials
- dependency outages

**Deliverables:**
- Integration tests complete
- 70%+ coverage target reached

---

### **Day 13: Saturday - Environment and Docker**
**Goal:** Prepare reproducible local and deployment setup

#### Morning (4 hours)
**Task 13.1: Environment Management**
- Create `.env.example`
- Add startup config validation
- Add environment profiles

#### Afternoon (4 hours)
**Task 13.2: Docker Setup**
- Create `Dockerfile`
- Create `docker-compose.yml`
- Add startup scripts

**Testing:**
- Build image and run stack
- API smoke tests in container

**Deliverables:**
- Complete environment templates
- Dockerized backend

---

### **Day 14: Sunday - Documentation and Final Polish**
**Goal:** Finalize docs, quality, and release package

#### Morning (4 hours)
**Task 14.1: API Documentation**
- Finalize OpenAPI metadata
- Add examples and auth notes

#### Afternoon (4 hours)
**Task 14.2: Documentation Completion**
- Create:
  - `docs/API.md`
  - `docs/SETUP.md`
  - `docs/ARCHITECTURE.md`
  - `docs/DEPLOYMENT.md`
  - `docs/TROUBLESHOOTING.md`
- Final quality pass

**Deliverables:**
- Complete docs package
- final tested build
- release-ready baseline

---

## Detailed Technical Specifications

### Database Schema (Portable Target)
```sql
Tables:
- users (id, email, full_name, password_hash, role, is_active)
- customers (id, email, full_name, phone, company, status, metadata)
- leads (id, owner_id, name, source, status, score, score_reason, created_at)
- deals (id, lead_id, owner_id, stage, value, expected_close_at, lost_reason)
- tasks (id, entity_type, entity_id, assigned_to, status, due_at, priority)
- messages (id, entity_type, entity_id, channel, sender_type, content, metadata)
- notifications (id, from_user, to_user, type, reference_type, reference_id, read)
- call_logs (id, provider, direction, from_number, to_number, status, recording_url)
- meeting_transcripts (id, call_log_id, transcript, summary, action_items_json)
- ai_interactions (id, module, prompt, response, model, latency_ms, token_usage, status)
```

### API Endpoints Inventory

#### Authentication (`/api/auth`)
- POST /auth/register
- POST /auth/login
- POST /auth/refresh
- POST /auth/logout
- GET /auth/me

#### Users (`/api/users`)
- GET /users
- GET /users/{id}
- POST /users
- PATCH /users/{id}
- DELETE /users/{id}

#### CRM (`/api`)
- CRUD for customers/leads/deals/tasks/messages
- GET /entities/{type}/{id}/timeline
- POST /leads/{id}/convert-to-deal

#### Telephony (`/api/telephony`)
- POST /telephony/twilio/webhook
- POST /telephony/exotel/webhook
- GET /calls/{id}

#### AI (`/api/ai`)
- POST /ai/lead-score
- POST /ai/suggest-response
- POST /ai/meeting-summary

#### Health (`/`)
- GET /
- GET /health
- GET /metrics

---

## Technology Stack Details

### Core Framework
- FastAPI
- Uvicorn
- Pydantic v2

### Database
- PostgreSQL (or Supabase Postgres)
- SQLAlchemy 2.x
- Alembic

### Authentication
- python-jose
- passlib[bcrypt]

### AI/LLM
- OpenAI SDK / Ollama / Anthropic / Gemini (via adapter)
- Optional LangChain for orchestration if needed

### Testing
- pytest
- pytest-asyncio
- pytest-cov
- httpx

### Code Quality
- black
- flake8 or ruff
- mypy
- pre-commit

### Optional Production
- redis
- celery or arq
- sentry-sdk
- prometheus-client

---

## Performance Targets

### API Performance
```
Metric                    | Target
--------------------------|------------------
Average Response Time     | < 120ms
95th Percentile           | < 250ms
99th Percentile           | < 600ms
Database Query Time       | < 60ms
AI Operation Time         | < 3s
```

### Test Coverage
```
Module                    | Target
--------------------------|------------------
Overall Coverage          | 70%+
Core Business Logic       | 85%+
API Endpoints             | 80%+
Authentication            | 90%+
```

---

## Security Checklist

### Authentication and Authorization
- JWT with expiry and refresh
- Secure password hashing
- RBAC guards for all protected routes

### Input and Network Security
- Strict request validation
- SQL injection and XSS protections
- CORS and security headers
- Rate limiting
- Webhook signature checks

### Operational Security
- PII-safe logs
- secret management via env
- dependency and vulnerability checks

---

## Deliverables Summary

### Code Deliverables
1. Authentication and RBAC
2. Repository and migration layer
3. Ported CRM domain services (lead/deal/task)
4. Activity and notification services
5. Telephony and meeting ingestion
6. AI service abstraction and workflows
7. Integration tests and hardening
8. Dockerized deployment

### Documentation Deliverables
1. API.md
2. SETUP.md
3. ARCHITECTURE.md
4. DEPLOYMENT.md
5. TROUBLESHOOTING.md
6. CONTRIBUTING.md
7. .env.example

### Configuration Deliverables
1. Dockerfile
2. docker-compose.yml
3. .dockerignore
4. pytest.ini
5. pyproject.toml
6. .pre-commit-config.yaml

---

## File Reuse Plan From This Codebase

### Category A: Reuse directly without changing
1. `crm/crm/tests/test_records.json`
2. `crm/README.md`
3. `crm/LICENSE`

### Category B: Reuse with modifications (what to change exactly)

1. `crm/crm/api/session.py`, `crm/crm/api/user.py`
- Replace Frappe role/session checks with JWT principal + RBAC decorators.

2. `crm/crm/fcrm/doctype/crm_lead/crm_lead.py`
- Move hook logic to explicit service methods.
- Replace assign/share APIs with assignment tables and ACL checks.

3. `crm/crm/fcrm/doctype/crm_deal/crm_deal.py`
- Port validation and transition rules to pure service layer.
- Replace DocType and DB APIs with SQLAlchemy repositories.

4. `crm/crm/fcrm/doctype/crm_task/crm_task.py`
- Port assignment and reassignment workflow to task assignment service.

5. `crm/crm/fcrm/doctype/crm_call_log/crm_call_log.py`
- Port call model and status mapping to SQL schema and services.

6. `crm/crm/integrations/api.py`
- Replace `frappe.whitelist` and doc methods with FastAPI endpoints.
- Keep phone-matching and linkage logic.

7. `crm/crm/integrations/twilio/api.py`, `crm/crm/integrations/exotel/handler.py`
- Replace webhook validation with provider signature middleware.
- Keep call direction, status mapping, and recording update behavior.

8. `crm/crm/api/activities.py`
- Replace `get_docinfo` dependency with event tables and aggregator query service.

9. `crm/crm/api/comment.py`, `crm/crm/api/notifications.py`, `crm/crm/fcrm/doctype/crm_notification/crm_notification.py`
- Replace realtime publish with Redis pub/sub + FastAPI websocket.
- Keep mention extraction and notification dedupe logic.

10. `crm/crm/api/doc.py`, `crm/crm/api/views.py`
- Port generic list/filter/group-by to secure whitelisted query builder.

11. `crm/crm/api/dashboard.py`
- Port analytics query logic and add AI KPI metrics.

12. `crm/crm/hooks.py`, `crm/crm/lead_syncing/background_sync.py`, `crm/crm/api/event.py`
- Replace Frappe scheduler with Celery Beat/Arq jobs.
- Keep periodic job semantics and retry behavior.

---

## Post-2-Week Roadmap

### Week 3-4
- Full meeting transcript summarization
- AI action-item extraction and auto-task creation
- Dashboard KPI expansions

### Week 5-6
- Caching and queue tuning
- Load and stress testing
- reliability hardening

### Week 7-8
- Multi-tenant foundations
- policy-driven AI governance
- release workflow automation

---

## Best Practices and Guidelines

### Coding Standards
1. Follow PEP 8
2. Use type hints across modules
3. Keep service methods single-responsibility
4. Prefer domain logic in services, not routers

### API and Data
1. Keep endpoints REST-consistent
2. Validate all input at schema boundary
3. Use Alembic for every schema change
4. Keep backward compatibility notes per API change

### Security
1. Never commit secrets
2. No sensitive data in logs
3. Verify all webhook signatures
4. Regular dependency updates

---

## Progress Tracking

### Daily Standup Questions
1. What did I complete yesterday?
2. What will I work on today?
3. Are there blockers?
4. What needs review/decision?

### Definition of Done
1. Code implemented
2. Unit tests passing
3. Integration tests passing
4. Documentation updated
5. Lint/type checks passing
6. Security checks completed

---

## Development Environment Setup

### Prerequisites
- Python 3.10+
- PostgreSQL (or Supabase)
- Redis
- Docker
- LLM API key(s)

### Initial Setup
```bash
git clone <repo-url>
cd AutoCRM/backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
pytest
```

---

## Support and Resources

- FastAPI docs
- SQLAlchemy docs
- Alembic docs
- Provider SDK docs (OpenAI/Ollama/Anthropic/Gemini)
- pytest docs

---

## Conclusion

This plan follows the same structure as your previous 2-week plan, but it is adapted to your strict portability requirement:
- no Frappe Bench
- no Frappe runtime coupling
- clear file reuse matrix with exact modification guidance

It is aggressive but feasible for a strong foundational backend in 14 days.

---

**Last Updated:** March 19, 2026
**Version:** 2.0
**Status:** Ready for Implementation
