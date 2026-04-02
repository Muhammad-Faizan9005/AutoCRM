# 🤖 AutoCRM

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green?style=for-the-badge&logo=fastapi&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-Database-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)

**AI-Powered Customer Relationship Management System**

[Features](#-features) • [Installation](#-installation) • [API Documentation](#-api-documentation) • [Architecture](#-architecture) • [Contributing](#-contributing)

</div>

---

## 📋 Overview

AutoCRM is an intelligent Customer Relationship Management system that leverages AI/LLM capabilities to automate and enhance customer support operations. Built as a Final Year Project, it demonstrates the integration of modern AI technologies with traditional CRM functionality.

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

### AI-Powered Features

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
| **Database**       | Supabase (PostgreSQL)                                |
| **AI/LLM**         | Configurable (OpenAI, Anthropic, Gemini, Local LLMs) |
| **Authentication** | JWT, Supabase Auth                                   |
| **API Docs**       | OpenAPI/Swagger                                      |

---

## 🚀 Installation

### Prerequisites

- Python 3.10 or higher
- Supabase account (free tier works)
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
   cp .env.example .env
   # Edit .env with your credentials
   ```

5. **Set up Supabase database**
   - Create a new project at [supabase.com](https://supabase.com)
   - Go to SQL Editor and run the schema from `database/schema.sql`
   - Copy your project URL and anon key to `.env`

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
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI application entry
│   │   ├── config.py         # Settings & environment config
│   │   ├── database.py       # Supabase client connection
│   │   ├── routers/          # API route handlers
│   │   │   ├── customers.py
│   │   │   ├── tickets.py
│   │   │   └── ai.py
│   │   ├── schemas/          # Pydantic models
│   │   │   ├── customer.py
│   │   │   └── ticket.py
│   │   ├── services/         # Business logic
│   │   └── models/           # Database models
│   ├── database/
│   │   └── schema.sql        # Database schema
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

### Customers

| Method   | Endpoint              | Description         |
| -------- | --------------------- | ------------------- |
| `GET`    | `/api/customers`      | List all customers  |
| `GET`    | `/api/customers/{id}` | Get customer by ID  |
| `POST`   | `/api/customers`      | Create new customer |
| `PATCH`  | `/api/customers/{id}` | Update customer     |
| `DELETE` | `/api/customers/{id}` | Delete customer     |

### Tickets

| Method   | Endpoint                     | Description           |
| -------- | ---------------------------- | --------------------- |
| `GET`    | `/api/tickets`               | List all tickets      |
| `GET`    | `/api/tickets/{id}`          | Get ticket by ID      |
| `POST`   | `/api/tickets`               | Create new ticket     |
| `PATCH`  | `/api/tickets/{id}`          | Update ticket         |
| `DELETE` | `/api/tickets/{id}`          | Delete ticket         |
| `GET`    | `/api/tickets/{id}/messages` | Get ticket messages   |
| `POST`   | `/api/tickets/{id}/messages` | Add message to ticket |

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

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│  customers   │     │   tickets    │     │  ticket_messages │
├──────────────┤     ├──────────────┤     ├──────────────────┤
│ id (PK)      │◄────│ customer_id  │◄────│ ticket_id        │
│ email        │     │ id (PK)      │     │ id (PK)          │
│ full_name    │     │ subject      │     │ sender_type      │
│ phone        │     │ description  │     │ content          │
│ company      │     │ status       │     │ created_at       │
│ status       │     │ priority     │     └──────────────────┘
│ created_at   │     │ ai_summary   │
└──────────────┘     │ ai_sentiment │
                     └──────────────┘
```

---

## ⚙️ Configuration

### Environment Variables

| Variable                          | Description                                 | Required              |
| --------------------------------- | ------------------------------------------- | --------------------- |
| `SUPABASE_URL`                    | Supabase project URL                        | ✅                    |
| `SUPABASE_KEY`                    | Supabase anon/public key                    | ✅                    |
| `DATABASE_URL`                    | PostgreSQL URL for Alembic migrations       | ✅ (for migrations)   |
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

---

## 🗺 Roadmap

- [x] Project setup & FastAPI configuration
- [x] Supabase database integration
- [x] Customer CRUD operations
- [x] Ticket management system
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

## 👨‍💻 Author

**Final Year Project**

---

<div align="center">

⭐ Star this repo if you find it helpful!

</div>
