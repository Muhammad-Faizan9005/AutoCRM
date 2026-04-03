from __future__ import annotations

from typing import Any

from supabase import Client

from app.repositories.base import BaseRepository


class CustomerRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="customers", resource_name="Customer")

    async def list_customers(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = {"status": status} if status else None
        return await self.list(skip=skip, limit=limit, filters=filters)
