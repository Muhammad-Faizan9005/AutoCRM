from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError, ResourceNotFoundError


class BaseRepository:
    """Generic repository with common CRUD operations for Supabase tables."""

    def __init__(self, db: Client, table_name: str, resource_name: str):
        self.db = db
        self.table_name = table_name
        self.resource_name = resource_name

    async def _execute(self, operation: Callable[[], Any]) -> Any:
        try:
            return await run_db_operation(operation)
        except Exception as exc:
            raise DatabaseError(detail=f"Failed DB operation on {self.table_name}") from exc

    @staticmethod
    def _normalize_id(record_id: Any) -> str:
        return str(record_id)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """
        Transaction boundary placeholder.

        Supabase Python client does not expose a direct multi-statement transaction API.
        Keep this context manager to retain a portable repository contract that can later
        map to SQLAlchemy/PostgreSQL transaction sessions.
        """
        yield

    async def list(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        order_desc: bool = False,
    ) -> list[dict[str, Any]]:
        query = self.db.table(self.table_name).select("*")

        if filters:
            for column, value in filters.items():
                if value is not None:
                    query = query.eq(column, value)

        if order_by:
            query = query.order(order_by, desc=order_desc)

        response = await self._execute(lambda: query.range(skip, skip + limit - 1).execute())
        return response.data or []

    async def get_by_id(self, record_id: Any) -> dict[str, Any]:
        response = await self._execute(
            lambda: self.db.table(self.table_name)
            .select("*")
            .eq("id", self._normalize_id(record_id))
            .limit(1)
            .execute()
        )

        rows = response.data or []
        if not rows:
            raise ResourceNotFoundError(self.resource_name, self._normalize_id(record_id))

        return rows[0]

    async def find_one(self, *, filters: dict[str, Any]) -> dict[str, Any] | None:
        query = self.db.table(self.table_name).select("*")
        for column, value in filters.items():
            query = query.eq(column, value)

        response = await self._execute(lambda: query.limit(1).execute())
        rows = response.data or []
        return rows[0] if rows else None

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._execute(lambda: self.db.table(self.table_name).insert(payload).execute())
        rows = response.data or []
        if not rows:
            raise DatabaseError(detail=f"Failed to create {self.resource_name}")
        return rows[0]

    async def update_by_id(self, record_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._execute(
            lambda: self.db.table(self.table_name)
            .update(payload)
            .eq("id", self._normalize_id(record_id))
            .execute()
        )

        rows = response.data or []
        if not rows:
            raise ResourceNotFoundError(self.resource_name, self._normalize_id(record_id))

        return rows[0]

    async def delete_by_id(self, record_id: Any) -> None:
        response = await self._execute(
            lambda: self.db.table(self.table_name)
            .delete()
            .eq("id", self._normalize_id(record_id))
            .execute()
        )

        rows = response.data or []
        if not rows:
            raise ResourceNotFoundError(self.resource_name, self._normalize_id(record_id))
