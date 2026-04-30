from __future__ import annotations

from typing import Any

from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="organizations", resource_name="Organization")

    async def list_organizations(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        industry: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            query = self.db.table(self.table_name).select("*")
            if industry:
                query = query.eq("industry", industry)
            if search:
                query = query.ilike("name", f"%{search}%")

            query = query.order("created_at", desc=True).range(skip, skip + limit - 1)
            response = await run_db_operation(lambda: query.execute())
        except Exception as exc:
            raise DatabaseError(detail="Failed to list organizations") from exc

        return response.data or []
