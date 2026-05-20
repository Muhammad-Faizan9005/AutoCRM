from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import get_db, run_db_operation
from app.middleware.error_handler import error_handler_middleware, setup_exception_handlers
from app.middleware.logging_middleware import logging_middleware
from app.middleware.rate_limiter import rate_limit_middleware
from app.middleware.security import security_middleware
from app.utils.logger import configure_logging


configure_logging(settings.DEBUG)

app = FastAPI(
    title="AutoCRM API",
    description="AI-Powered Customer Relationship Management System",
    version="1.0.0"
)

# CORS middleware for frontend integration — register early so preflight
# requests receive CORS headers before any custom middleware intercepts them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://auto-crm-frontend-pink.vercel.app",
        "https://auto-crm-frontend-henna.vercel.app"
    ],  # only allow known frontend origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware registration order matters.
# Last registered executes first, so request-id gets attached before request logs.
app.middleware("http")(security_middleware)
app.middleware("http")(rate_limit_middleware)
app.middleware("http")(logging_middleware)
app.middleware("http")(error_handler_middleware)

# Setup exception handlers
setup_exception_handlers(app)


@app.on_event("startup")
async def warmup_database_metadata() -> None:
    # Preload metadata used during auth flows so first login is not penalized.
    db = get_db()
    await run_db_operation(
        lambda: db.warmup_tables(["agents", "agent_permissions", "revoked_tokens"])
    )

@app.get("/")
async def root():
    return {"message": "Welcome to AutoCRM an Agentic AI Enabled CRM System", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Include routers
from app.routers import auth, customers, deals, imports, leads, notes, organizations, tasks, tickets, users, dashboard, admin, teams, notifications

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(customers.router, prefix="/api/customers", tags=["Customers"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["Tickets"])
app.include_router(imports.router, prefix="/api/import", tags=["Import"])
app.include_router(leads.router, prefix="/api/leads", tags=["Leads"])
app.include_router(deals.router, prefix="/api/deals", tags=["Deals"])
app.include_router(organizations.router, prefix="/api/organizations", tags=["Organizations"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["Tasks"])
app.include_router(notes.router, prefix="/api/notes", tags=["Notes"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(teams.router, prefix="/api/admin/teams", tags=["Teams"])
