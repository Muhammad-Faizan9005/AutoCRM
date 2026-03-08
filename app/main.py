from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.middleware.error_handler import setup_exception_handlers

app = FastAPI(
    title="AutoCRM API",
    description="AI-Powered Customer Relationship Management System",
    version="1.0.0"
)

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
from app.routers import customers, tickets, auth

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(customers.router, prefix="/api/customers", tags=["Customers"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["Tickets"])
