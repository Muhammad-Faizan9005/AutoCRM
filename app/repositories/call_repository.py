from __future__ import annotations

from typing import Any

from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError
from app.repositories.base import BaseRepository


class CallRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="call_sessions", resource_name="Call session")

    async def list_calls_by_lead(
        self,
        *,
        lead_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            query = (
                self.db.table(self.table_name)
                .select("*")
                .eq("lead_id", lead_id)
                .order("started_at", desc=True)
                .range(skip, skip + limit - 1)
            )
            response = await run_db_operation(lambda: query.execute())
        except Exception as exc:
            raise DatabaseError(detail="Failed to list call sessions") from exc

        return response.data or []
