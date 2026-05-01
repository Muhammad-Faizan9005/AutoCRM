from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError, ResourceNotFoundError
from app.utils.retry import retry
from app.utils.circuit_breaker import get_db_circuit_breaker
from app.utils.cache import (
    get_cached_table_query,
    cache_table_query,
    invalidate_table_cache,
)


class BaseRepository:
    """Generic repository with common CRUD operations for Supabase tables."""

    def __init__(self, db: Client, table_name: str, resource_name: str):
        self.db = db
        self.table_name = table_name
        self.resource_name = resource_name

    async def _execute(self, operation: Callable[[], Any]) -> Any:
        """
        Execute a database operation with retry logic and circuit breaker.
        
        - Retry up to 3 times with exponential backoff for transient failures
        - Circuit breaker prevents cascading failures when DB is down
        """
        circuit_breaker = get_db_circuit_breaker()
        
        @retry(max_retries=3, initial_delay_ms=100, backoff_multiplier=2.5, max_delay_ms=5000)
        async def _operation_with_retry():
            return await run_db_operation(operation)
        
        try:
            # Execute with circuit breaker protection
            return await circuit_breaker.call(_operation_with_retry)
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

        # Build cache key for this table list query
        filters_key = (
            "+".join(f"{k}:{v}" for k, v in sorted((filters or {}).items())) if filters else ""
        )
        order_key = f"order:{order_by}:{order_desc}" if order_by else ""
        cache_key = f"table:{self.table_name}:list:skip={skip}:limit={limit}:{filters_key}:{order_key}"

        cached = get_cached_table_query(cache_key)
        if cached is not None:
            return cached

        response = await self._execute(lambda: query.range(skip, skip + limit - 1).execute())
        data = response.data or []

        # Cache the list result for short TTL
        cache_table_query(cache_key, data, ttl_seconds=60)
        return data

    async def get_by_id(self, record_id: Any) -> dict[str, Any]:
        cache_key = f"table:{self.table_name}:id:{self._normalize_id(record_id)}"
        cached = get_cached_table_query(cache_key)
        if cached is not None:
            return cached

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

        # Cache single-row result
        cache_table_query(cache_key, rows[0], ttl_seconds=300)
        return rows[0]

    async def find_one(self, *, filters: dict[str, Any]) -> dict[str, Any] | None:
        query = self.db.table(self.table_name).select("*")
        for column, value in filters.items():
            query = query.eq(column, value)
        # Cache single-find with filters
        filters_key = "+".join(f"{k}:{v}" for k, v in sorted(filters.items()))
        cache_key = f"table:{self.table_name}:find_one:{filters_key}"
        cached = get_cached_table_query(cache_key)
        if cached is not None:
            return cached

        response = await self._execute(lambda: query.limit(1).execute())
        rows = response.data or []
        result = rows[0] if rows else None
        cache_table_query(cache_key, result, ttl_seconds=60)
        return result

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._execute(lambda: self.db.table(self.table_name).insert(payload).execute())
        rows = response.data or []
        if not rows:
            raise DatabaseError(detail=f"Failed to create {self.resource_name}")

        # Invalidate table-level caches on write
        try:
            invalidate_table_cache(self.table_name)
        except Exception:
            pass
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

        # Invalidate cache for this table and specific id
        try:
            invalidate_table_cache(self.table_name)
            cache_key = f"table:{self.table_name}:id:{self._normalize_id(record_id)}"
            get_cache = __import__("app.utils.cache", fromlist=["get_cache"]).get_cache
            get_cache().invalidate(cache_key)
        except Exception:
            pass
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

        # Invalidate table cache and id-specific cache
        try:
            invalidate_table_cache(self.table_name)
            cache_key = f"table:{self.table_name}:id:{self._normalize_id(record_id)}"
            get_cache = __import__("app.utils.cache", fromlist=["get_cache"]).get_cache
            get_cache().invalidate(cache_key)
        except Exception:
            pass
