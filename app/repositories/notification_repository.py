from __future__ import annotations

from typing import Any

from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="notifications", resource_name="Notification")

    async def list_for_user(
        self,
        *,
        recipient_id: str,
        skip: int = 0,
        limit: int = 50,
        unread_only: bool = False,
    ) -> list[dict[str, Any]]:
        try:
            query = self.db.table(self.table_name).select("*").eq("recipient_id", recipient_id)
            if unread_only:
                query = query.is_("read_at", None)
            query = query.order("created_at", desc=True).range(skip, skip + limit - 1)
            response = await run_db_operation(lambda: query.execute())
        except Exception as exc:
            raise DatabaseError(detail="Failed to list notifications") from exc

        return response.data or []
