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

AutoCRM is a Customer Relationship Management backend built with FastAPI and PostgreSQL. The current implementation delivers production-oriented CRM fundamentals (auth, RBAC, admin console, invites, imports, calls, and security middleware) plus backend control-plane APIs used by the AI service.

### 🎯 Problem Statement

Traditional CRM systems require significant manual effort for:

- Categorizing and prioritizing support tickets
- Generating appropriate responses
- Analyzing customer sentiment
- Extracting actionable insights from conversations

AutoCRM addresses these challenges by integrating AI-powered automation.

### Current AI + Call Capabilities

- **AI Control Plane** - Agent runs, traces, approvals, settings, team stats, and AI agent credentials.
- **Lead + Deal Insights** - AI scoring, risk alerts, summaries, and suggested next actions.
- **Human Approval Flow** - AI actions are proposed to backend APIs before CRM writes are applied.
- **Call Rooms + Recordings** - Authenticated call start/end flows, recording upload, and protected playback.
- **Meeting Intelligence Hooks** - Backend notification path for AI transcription and follow-up workflows.

---

## ✨ Features

### Core CRM Features

- 👥 **Customer Management** - Customer profiles, statuses, and history
- 📌 **Lead & Deal Tracking** - Pipeline-ready lead and deal management
- 🏢 **Organization Management** - Company profiles and metadata
- 📝 **Notes & Tasks** - Notes, task assignment, and due-date tracking
- 🎫 **Ticket System** - Ticket lifecycle with threaded messages
- 👨‍💼 **Admin Console** - Users, teams, permissions, and imports
- 📬 **Invites + Re-invite Flow** - Invite lifecycle with failed-invites recovery
- 🔐 **RBAC + Permissions** - Role defaults plus per-user overrides
- 🧱 **Repository Architecture** - Centralized data access layer
- 🛡️ **Security Hardening** - Request IDs, structured logs, rate limits, secure headers

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
- Mailjet keys (for invites)

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

   ```bash
   python -m alembic upgrade head
   python -m alembic current
   ```

6. **Run the server**

   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

7. **Access the API**
   - API: http://localhost:8000
   - Swagger Docs: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

---

## ⚙️ Environment Variables

Core:

```env
DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<db>?sslmode=require
JWT_SECRET_KEY=<min-32-char-secret>
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
```

Invites + email:

```env
MAILJET_API_KEY=
MAILJET_SECRET_KEY=
MAILJET_SENDER_EMAIL=
MAILJET_SENDER_NAME=AutoCRM
FRONTEND_BASE_URL=http://localhost:5173
INVITE_TOKEN_TTL_HOURS=72
```

Optional AI:

```env
LLM_API_KEY=
LLM_MODEL=gpt-4
LLM_BASE_URL=
AI_SERVICE_BASE_URL=http://localhost:8001
AI_SERVICE_WEBHOOK_TOKEN=<shared-dev-token>
AUTOCRM_AI_AGENT_KEY=<agent-key>
AUTOCRM_AI_SERVICE_TOKEN=<agent-service-token>
```

Operational limits:

```env
CALL_RECORDINGS_DIR=storage/recordings
CALL_RECORDING_CHUNK_MAX_BYTES=5000000
CALL_RECORDING_MAX_BYTES=100000000
IMPORT_MAX_FILE_BYTES=5000000
IMPORT_MAX_ROWS=5000
```

---

## Current Security Notes

- `DEBUG=True` is acceptable for local development. For staging or production, set production-safe values for debug, CORS origins, JWT secrets, webhook tokens, and database credentials.
- Public static exposure is limited to `/static/avatars`. Call recordings are not mounted as static files; clients should use authenticated playback through `GET /api/calls/{call_id}/recording/file`.
- AI agent endpoints support authenticated human users and AI service credentials. Configure `AUTOCRM_AI_AGENT_KEY`, `AUTOCRM_AI_SERVICE_TOKEN`, and `AI_SERVICE_WEBHOOK_TOKEN` for service-to-service traffic.
- Import and recording uploads are bounded by configurable size and row limits to avoid accidental memory pressure.
- Keep real credentials only in `.env` or a secret manager. Do not put live DB, Supabase, Mailjet, JWT, AI-service, or service-account values into docs.

---

## 📁 Project Structure

```
AutoCRM/
├── backend/
│   ├── alembic/                  # Alembic environment + revision scripts
│   ├── app/
│   │   ├── main.py                # FastAPI application entry
│   │   ├── config.py              # Settings & environment config
│   │   ├── database.py            # Database client bootstrap
│   │   ├── postgres_client.py     # PostgreSQL query adapter
│   │   ├── auth/                  # JWT helpers, dependencies, token revocation
│   │   ├── middleware/            # Error handling, logging, security, rate limiting
│   │   ├── repositories/          # Data access layer
│   │   ├── routers/               # API route handlers
│   │   ├── schemas/               # Pydantic models
│   │   ├── services/              # Business logic
│   │   └── utils/                 # Utilities and helpers
│   ├── database/
│   │   ├── schema.sql             # Base schema
│   │   ├── migrations/            # Raw SQL migration notes/scripts
│   │   └── seeds/
│   ├── docs/                      # API docs and guides
│   ├── storage/                   # Permissions JSON (per user)
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

### Admin Users

| Method   | Endpoint                              | Description                        |
| -------- | ------------------------------------- | ---------------------------------- |
| `GET`    | `/api/admin/users`                    | List users (admin/manager)         |
| `POST`   | `/api/admin/users`                    | Create user/invite                 |
| `PATCH`  | `/api/admin/users/{user_id}`          | Update user                        |
| `DELETE` | `/api/admin/users/{user_id}`          | Disable user                       |
| `GET`    | `/api/admin/users/{user_id}/permissions` | Get permissions                 |
| `PUT`    | `/api/admin/users/{user_id}/permissions` | Update permissions              |

### Failed Invites

| Method   | Endpoint                                      | Description            |
| -------- | --------------------------------------------- | ---------------------- |
| `GET`    | `/api/admin/failed-invites`                   | List failed invites    |
| `POST`   | `/api/admin/failed-invites/{id}/reinvite`     | Re-invite              |
| `DELETE` | `/api/admin/failed-invites/{id}`              | Delete failed invite   |

### Teams

| Method   | Endpoint                         | Description                |
| -------- | -------------------------------- | -------------------------- |
| `GET`    | `/api/admin/teams`               | List teams                 |
| `POST`   | `/api/admin/teams`               | Create team                |
| `PATCH`  | `/api/admin/teams/{team_id}`     | Rename team                |
| `DELETE` | `/api/admin/teams/{team_id}`     | Delete team                |

### Data Import

| Method | Endpoint                | Description                                       |
| ------ | ----------------------- | ------------------------------------------------- |
| `POST` | `/api/import/customers` | Bulk import customers from CSV/XLSX (manager+)    |
| `POST` | `/api/import/tickets`   | Bulk import tickets from CSV/XLSX (manager/admin) |

---

## 🗄 Database Schema

Core tables currently used by the backend:

- `customers`
- `tickets`
- `ticket_messages`
- `agents`
- `permissions`
- `failed_invites`
- `teams` + `team_members`
- `revoked_tokens`

---

## 🤝 Contributing

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
