# 🤖 AutoCRM

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)

**AI-Ready Customer Relationship Management System**

[Features](#-features) • [Installation](#-installation) • [API Documentation](#-api-documentation) • [Project Structure](#-project-structure) • [Contributing](#-contributing)

</div>

---

## 📋 Overview

AutoCRM is a Customer Relationship Management backend built with FastAPI and PostgreSQL. The current implementation delivers production-oriented CRM fundamentals (auth, RBAC, CRUD, imports, security middleware), while AI/LLM features are scaffolded and planned in the roadmap.

### 🎯 Problem Statement

Traditional CRM systems require significant manual effort for:

- Categorizing and prioritizing support tickets
- Generating appropriate responses
- Analyzing customer sentiment
- Extracting actionable insights from conversations

AutoCRM addresses these challenges by integrating AI-powered automation.

---

## ✨ Features

### Core CRM Features

- 👥 **Customer Management** - Complete customer profiles with contact info, company details, and interaction history
- 🎫 **Ticket System** - Full-featured support ticket lifecycle management
- 💬 **Conversation Threads** - Threaded messaging for each ticket with agent/customer/AI attribution
- 👨‍💼 **Agent Management** - Role-based access for admins, sales managers, and sales reps
- 🧱 **Repository Architecture** - Centralized data access layer with reusable CRUD and error mapping
- 🛡️ **Security Hardening** - Request correlation IDs, structured logs, rate limiting, request-size guard, and secure headers

### Planned AI Features

- 🧠 **Smart Ticket Categorization** - Automatic classification of incoming tickets
- 📊 **Sentiment Analysis** - Real-time customer mood detection
- 💡 **AI Response Suggestions** - Context-aware reply recommendations
- 📝 **Automatic Summarization** - Concise summaries of long conversation threads
- 📈 **Analytics & Insights** - AI-driven reporting and trend analysis

---

## 🛠 Tech Stack

| Layer              | Technology                                           |
| ------------------ | ---------------------------------------------------- |
| **Backend**        | Python, FastAPI                                      |
| **Database**       | PostgreSQL (Supabase/Neon/managed Postgres)          |
| **AI/LLM**         | Configurable (OpenAI, Anthropic, Gemini, Local LLMs) |
| **Authentication** | JWT, RBAC, refresh-token rotation + revocation       |
| **API Docs**       | OpenAPI/Swagger                                      |

---

## 🚀 Installation

### Prerequisites

- Python 3.10 or higher
- PostgreSQL database URL (Supabase, Neon, or another managed PostgreSQL)
- LLM API key (optional, for AI features)

### Quick Start

1. **Clone the repository**

   ```bash
   git clone https://github.com/yourusername/AutoCRM.git
   cd AutoCRM
   ```

2. **Set up Python environment**

   ```bash
   cd backend
   python -m venv venv

   # Windows
   venv\Scripts\activate

   # macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   ```bash
   # macOS/Linux
   cp .env.example .env

   # Windows PowerShell
   Copy-Item .env.example .env

   # Edit .env with your credentials
   ```

5. **Set `DATABASE_URL` and run migrations**
   - Fill `.env` with one PostgreSQL connection string:
       - Supabase pooler example: `DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-<region>.pooler.supabase.com:6543/postgres?sslmode=require`
       - Neon example: `DATABASE_URL=postgresql://<user>:<password>@<endpoint>.neon.tech/<database>?sslmode=require`
   - Apply schema/migrations:

   ```bash
   python -m alembic upgrade head
   python -m alembic current
   ```

   Note: on a fresh database, migration `945b9872d621` bootstraps the base schema automatically.

6. **Run the server**

   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

7. **Access the API**
   - API: http://localhost:8000
   - Swagger Docs: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

---

## 📁 Project Structure

```
AutoCRM/
├── backend/
│   ├── alembic/                  # Alembic environment + revision scripts
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI application entry
│   │   ├── config.py         # Settings & environment config
│   │   ├── database.py       # Database client bootstrap (DATABASE_URL)
│   │   ├── postgres_client.py# PostgreSQL query adapter
│   │   ├── auth/             # JWT helpers, dependencies, token revocation
│   │   ├── middleware/       # Error handling, logging, security, rate limiting
│   │   ├── repositories/     # Data access layer
│   │   ├── routers/          # API route handlers
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── customers.py
│   │   │   ├── imports.py
│   │   │   ├── tickets.py
│   │   ├── schemas/          # Pydantic models
│   │   │   ├── auth.py
│   │   │   ├── customer.py
│   │   │   ├── imports.py
│   │   │   ├── ticket.py
│   │   │   └── user.py
│   │   ├── services/         # Business logic
│   │   │   └── import_service.py
│   │   └── ...               # Validators, utils, exceptions
│   ├── database/
│   │   ├── schema.sql        # Base schema
│   │   ├── migrations/       # Raw SQL migration notes/scripts
│   │   └── seeds/
│   ├── docs/
│   │   └── API.md            # Implementation-accurate API contract
│   ├── tests/
│   ├── requirements.txt
│   ├── .env.example
│   └── .env
└── README.md
```

---

## 📖 API Documentation

For implementation-accurate endpoint contracts, payload examples, auth flow, and frontend integration requirements, use:

- `docs/API.md`
- `FRONTEND_INTEGRATION_GUIDE.md`

### Authentication

| Method | Endpoint            | Description                |
| ------ | ------------------- | -------------------------- |
| `POST` | `/api/auth/register`| Register and return tokens |
| `POST` | `/api/auth/login`   | Login and return tokens    |
| `GET`  | `/api/auth/me`      | Current user profile       |
| `POST` | `/api/auth/refresh` | Rotate access/refresh pair |
| `POST` | `/api/auth/logout`  | Revoke current token(s)    |

### Users

| Method   | Endpoint                | Description                    |
| -------- | ----------------------- | ------------------------------ |
| `GET`    | `/api/users/`           | List users (admin)             |
| `GET`    | `/api/users/{user_id}`  | Get user (admin or self)       |
| `POST`   | `/api/users/`           | Create user (admin)            |
| `PATCH`  | `/api/users/{user_id}`  | Update user (self/admin rules) |
| `DELETE` | `/api/users/{user_id}`  | Deactivate user (admin)        |

### Customers

| Method   | Endpoint              | Description         |
| -------- | --------------------- | ------------------- |
| `GET`    | `/api/customers`      | List all customers  |
| `GET`    | `/api/customers/{customer_id}` | Get customer by ID  |
| `POST`   | `/api/customers`      | Create new customer |
| `PATCH`  | `/api/customers/{customer_id}` | Update customer     |
| `DELETE` | `/api/customers/{customer_id}` | Delete customer     |

### Tickets

| Method   | Endpoint                     | Description           |
| -------- | ---------------------------- | --------------------- |
| `GET`    | `/api/tickets`               | List all tickets      |
| `GET`    | `/api/tickets/{ticket_id}`   | Get ticket by ID      |
| `POST`   | `/api/tickets`               | Create new ticket     |
| `PATCH`  | `/api/tickets/{ticket_id}`   | Update ticket         |
| `DELETE` | `/api/tickets/{ticket_id}`   | Delete ticket         |
| `GET`    | `/api/tickets/{ticket_id}/messages` | Get ticket messages   |
| `POST`   | `/api/tickets/{ticket_id}/messages` | Add message to ticket |

### Data Import

| Method | Endpoint                | Description                                       |
| ------ | ----------------------- | ------------------------------------------------- |
| `POST` | `/api/import/customers` | Bulk import customers from CSV/XLSX (manager+)    |
| `POST` | `/api/import/tickets`   | Bulk import tickets from CSV/XLSX (manager/admin) |

### Query Parameters

```
GET /api/customers?status=active&skip=0&limit=100
GET /api/tickets?status=open&priority=high&customer_id=uuid
```

---

## 🗄 Database Schema

Core tables currently used by the backend:

- `customers`
- `tickets`
- `ticket_messages`
- `agents`
- `revoked_tokens`
- `ai_interactions`

Source of truth SQL:

- `database/schema.sql`

---

## ⚙️ Configuration

### Environment Variables

| Variable                          | Description                                 | Required              |
| --------------------------------- | ------------------------------------------- | --------------------- |
| `DATABASE_URL`                    | PostgreSQL URL for API + Alembic (Supabase/Neon/managed Postgres) | ✅ |
| `LLM_API_KEY`                     | API key for LLM provider                    | ❌                    |
| `LLM_MODEL`                       | Model name (e.g., gpt-4, claude-3)          | ❌                    |
| `LLM_BASE_URL`                    | Custom endpoint for local LLMs              | ❌                    |
| `JWT_SECRET_KEY`                  | JWT signing key                             | ✅                    |
| `JWT_ALGORITHM`                   | JWT signing algorithm                       | ❌ (default: HS256)   |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token expiry in minutes              | ❌ (default: 30)      |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS`   | Refresh-token expiry in days                | ❌ (default: 7)       |
| `RATE_LIMIT_ENABLED`              | Enable/disable API rate limiting middleware | ❌ (default: True)    |
| `RATE_LIMIT_REQUESTS_PER_MINUTE`  | Per-IP, per-path request cap per minute     | ❌ (default: 120)     |
| `MAX_REQUEST_SIZE_BYTES`          | Maximum allowed HTTP request body size      | ❌ (default: 1048576) |
| `SECURITY_HEADERS_ENABLED`        | Enable security response headers            | ❌ (default: True)    |

Examples:
- Supabase pooler: `postgresql://postgres.<project-ref>:<password>@aws-<region>.pooler.supabase.com:6543/postgres?sslmode=require`
- Neon: `postgresql://<user>:<password>@<endpoint>.neon.tech/<database>?sslmode=require`

---

## 🗺 Roadmap

- [x] Project setup & FastAPI configuration
- [x] PostgreSQL database integration
- [x] JWT authentication + refresh flow
- [x] RBAC user management
- [x] Customer CRUD operations
- [x] Ticket management system
- [x] CSV/XLSX customer and ticket import
- [x] Security hardening middleware
- [ ] AI ticket categorization
- [ ] Sentiment analysis integration
- [ ] AI response suggestions
- [ ] Frontend dashboard (React/Next.js)
- [ ] Real-time notifications
- [ ] Analytics dashboard
- [ ] Multi-tenant support

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👨‍💻 Authors

| | Name |
|---|---|
| 👤 | Muhammad Faizan Haider |
| 👤 | Muhammad Tayyab |
| 👤 | Umer Shahid |
| 👤 | Iqra Mubarik |
---

<div align="center">

⭐ Star this repo if you find it helpful!

</div>
