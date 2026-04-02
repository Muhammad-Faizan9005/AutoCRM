from __future__ import annotations

from supabase import Client

from app.repositories.base import BaseRepository


class LeadRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="leads", resource_name="Lead")
