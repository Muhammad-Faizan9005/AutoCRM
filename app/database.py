from supabase import create_client, Client
from app.config import settings


def get_supabase_client() -> Client:
    """
    Create and return a Supabase client instance.
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")
    
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


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
