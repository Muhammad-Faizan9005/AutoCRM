import asyncio
from typing import Callable, TypeVar

from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.postgres_client import PostgresClient

T = TypeVar("T")


def get_database_client() -> PostgresClient:
    """Create and return a DB client from DATABASE_URL."""
    if not settings.DATABASE_URL:
        raise ValueError("DATABASE_URL must be set in environment variables")
    return PostgresClient(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    )


# Singleton client instance
db_client: PostgresClient | None = None
_db_operation_semaphore: asyncio.Semaphore | None = None


def _get_db_operation_semaphore() -> asyncio.Semaphore:
    global _db_operation_semaphore
    if _db_operation_semaphore is None:
        _db_operation_semaphore = asyncio.Semaphore(max(1, settings.DB_MAX_CONCURRENT_OPERATIONS))
    return _db_operation_semaphore


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
    async with _get_db_operation_semaphore():
        return await run_in_threadpool(operation)
