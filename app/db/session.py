from __future__ import annotations

from supabase import Client

from app.database import get_db


def get_db_session() -> Client:
    """
    Session-style accessor for compatibility with service/repository patterns.

    This keeps the codebase aligned with the planned app/db/session.py structure
    while using the configured active data client.
    """
    return get_db()
