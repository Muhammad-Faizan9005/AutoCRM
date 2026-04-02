from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
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

# Middleware registration order matters.
# Last registered executes first, so request-id gets attached before request logs.
app.middleware("http")(security_middleware)
app.middleware("http")(rate_limit_middleware)
app.middleware("http")(logging_middleware)
app.middleware("http")(error_handler_middleware)

# Setup exception handlers
setup_exception_handlers(app)

# CORS middleware for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Welcome to AutoCRM API", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Include routers
from app.routers import auth, customers, imports, tickets, users

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(customers.router, prefix="/api/customers", tags=["Customers"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["Tickets"])
app.include_router(imports.router, prefix="/api/import", tags=["Import"])
