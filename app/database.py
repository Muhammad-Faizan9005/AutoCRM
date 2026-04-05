from typing import Callable, TypeVar

from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.postgres_client import PostgresClient

T = TypeVar("T")


def get_database_client() -> PostgresClient:
    """Create and return a DB client from DATABASE_URL."""
    if not settings.DATABASE_URL:
        raise ValueError("DATABASE_URL must be set in environment variables")
    return PostgresClient(settings.DATABASE_URL)


# Singleton client instance
db_client: PostgresClient | None = None


def get_db() -> PostgresClient:
    """
    Dependency to get the configured DB client from DATABASE_URL.
    Use this in FastAPI routes with Depends(get_db)
    """
    global db_client
    if db_client is None:
        db_client = get_database_client()
    return db_client


async def run_db_operation(operation: Callable[[], T]) -> T:
    """Run synchronous DB operations in a thread to avoid event-loop blocking."""
    return await run_in_threadpool(operation)
