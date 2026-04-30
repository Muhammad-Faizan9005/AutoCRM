from __future__ import annotations

from typing import Any

from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError
from app.repositories.base import BaseRepository


class DealRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="deals", resource_name="Deal")

    async def list_deals(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        stage: str | None = None,
        owner_id: str | None = None,
        organization_id: str | None = None,
        lead_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            query = self.db.table(self.table_name).select("*")
            if stage:
                query = query.eq("stage", stage)
            if owner_id:
                query = query.eq("owner_id", owner_id)
            if organization_id:
                query = query.eq("organization_id", organization_id)
            if lead_id:
                query = query.eq("lead_id", lead_id)

            query = query.order("created_at", desc=True).range(skip, skip + limit - 1)
            response = await run_db_operation(lambda: query.execute())
        except Exception as exc:
            raise DatabaseError(detail="Failed to list deals") from exc

        return response.data or []
