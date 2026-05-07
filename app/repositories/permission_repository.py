from __future__ import annotations

from typing import Any

from supabase import Client

from app.exceptions.custom_exceptions import DatabaseError
from app.repositories.base import BaseRepository
from app.utils.cache import invalidate_table_cache


class PermissionRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="agent_permissions", resource_name="PermissionSet")

    async def get_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        return await self.find_one(filters={"user_id": str(user_id)})

    async def upsert_permission_file(self, user_id: str, permission_file: str) -> dict[str, Any]:
        payload = {"user_id": str(user_id), "permission_file": permission_file}
        response = await self._execute(
            lambda: self.db.table(self.table_name)
            .upsert(payload, on_conflict="user_id")
            .execute()
        )

        rows = response.data or []
        if not rows:
            raise DatabaseError(detail="Failed to update permissions")

        try:
            invalidate_table_cache(self.table_name)
        except Exception:
            pass

        return rows[0]
