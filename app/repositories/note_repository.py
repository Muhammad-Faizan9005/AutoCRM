from __future__ import annotations

from typing import Any

from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError
from app.repositories.base import BaseRepository


class NoteRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="notes", resource_name="Note")

    async def list_notes(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        entity_type: str | None = None,
        entity_id: str | None = None,
        author_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            query = self.db.table(self.table_name).select("*")
            if entity_type:
                query = query.eq("entity_type", entity_type)
            if entity_id:
                query = query.eq("entity_id", entity_id)
            if author_id:
                query = query.eq("author_id", author_id)

            query = query.order("created_at", desc=True).range(skip, skip + limit - 1)
            response = await run_db_operation(lambda: query.execute())
        except Exception as exc:
            raise DatabaseError(detail="Failed to list notes") from exc

        return response.data or []
