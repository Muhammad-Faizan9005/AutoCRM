from typing import Callable, TypeVar

from fastapi.concurrency import run_in_threadpool
from supabase import create_client, Client

from app.config import settings

T = TypeVar("T")


def get_supabase_client() -> Client:
    """
    Create and return a Supabase client instance.
    """
    supabase_key = settings.supabase_api_key
    if not settings.SUPABASE_URL or not supabase_key:
        raise ValueError(
            "SUPABASE_URL and one of SUPABASE_KEY/SUPABASE_SERVICE_ROLE_KEY/"
            "SUPABASE_ANON_KEY must be set in environment variables"
        )
    
    return create_client(settings.SUPABASE_URL, supabase_key)


# Singleton client instance
supabase: Client = None


def get_db() -> Client:
    """
    Dependency to get the Supabase client.
    Use this in FastAPI routes with Depends(get_db)
    """
    global supabase
    if supabase is None:
        supabase = get_supabase_client()
    return supabase


async def run_db_operation(operation: Callable[[], T]) -> T:
    """Run synchronous Supabase operations in a thread to avoid event-loop blocking."""
    return await run_in_threadpool(operation)
