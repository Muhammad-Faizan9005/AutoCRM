from __future__ import annotations

from supabase import Client

from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="agents", resource_name="User")

    async def find_by_email(self, email: str) -> dict | None:
        return await self.find_one(filters={"email": email})
