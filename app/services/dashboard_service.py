from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.postgres_client import PostgresClient
from app.utils.cache import get_cache


class DashboardService:
    def __init__(self, db: PostgresClient):
        self.db = db
        self._cache = get_cache()

    def _get_cache_key(self, query_type: str, days: int = 0) -> str:
        """Generate cache key for dashboard queries."""
        query_hash = hashlib.md5(query_type.encode()).hexdigest()[:8]
        return f"dashboard:{query_type}:{days}:{query_hash}"

    def _fetch_scalar(self, query: str, params: dict[str, Any] | None = None) -> Any:
        """Fetch single scalar value from query."""
        with self.db.engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            return result.scalar()

    def _fetch_grouped(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Fetch grouped results from query."""
        with self.db.engine.connect() as conn:
            rows = conn.execute(text(query), params or {}).mappings().all()
        return [dict(row) for row in rows]

    async def _fetch_scalar_async(
        self, query: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Fetch scalar value asynchronously (runs in thread pool)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fetch_scalar, query, params
        )

    async def _fetch_grouped_async(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Fetch grouped results asynchronously (runs in thread pool)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fetch_grouped, query, params
        )

    async def get_summary(self) -> dict[str, Any]:
        """
        Get dashboard summary with all queries executed in parallel.
        Results are cached for 60 seconds to reduce database load.
        """
        cache_key = self._get_cache_key("summary")
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Execute all queries in parallel
        (
            leads_total,
            deals_total,
            organizations_total,
            tasks_total,
            notes_total,
            revenue_total,
            pipeline,
            leads_by_status,
            tasks_by_status,
        ) = await asyncio.gather(
            self._fetch_scalar_async("SELECT COUNT(*) FROM leads"),
            self._fetch_scalar_async("SELECT COUNT(*) FROM deals"),
            self._fetch_scalar_async("SELECT COUNT(*) FROM organizations"),
            self._fetch_scalar_async("SELECT COUNT(*) FROM tasks"),
            self._fetch_scalar_async("SELECT COUNT(*) FROM notes"),
            self._fetch_scalar_async(
                "SELECT COALESCE(SUM(value), 0) FROM deals"
            ),
            self._fetch_grouped_async(
                """
                SELECT stage,
                       COUNT(*) AS count,
                       COALESCE(SUM(value), 0) AS value_total
                FROM deals
                GROUP BY stage
                ORDER BY stage
                """
            ),
            self._fetch_grouped_async(
                """
                SELECT status, COUNT(*) AS count
                FROM leads
                GROUP BY status
                ORDER BY status
                """
            ),
            self._fetch_grouped_async(
                """
                SELECT status, COUNT(*) AS count
                FROM tasks
                GROUP BY status
                ORDER BY status
                """
            ),
        )

        # Convert types
        for row in pipeline:
            row["value_total"] = float(row.get("value_total") or 0)

        result = {
            "leads_total": int(leads_total or 0),
            "deals_total": int(deals_total or 0),
            "organizations_total": int(organizations_total or 0),
            "tasks_total": int(tasks_total or 0),
            "notes_total": int(notes_total or 0),
            "revenue_total": float(revenue_total or 0),
            "pipeline": pipeline,
            "leads_by_status": leads_by_status,
            "tasks_by_status": tasks_by_status,
        }

        # Cache for 60 seconds
        self._cache.set(cache_key, result, ttl_seconds=60)
        return result

    async def get_activity(self, *, days: int = 14) -> dict[str, Any]:
        """
        Get activity data with all queries executed in parallel.
        Results are cached for 60 seconds.
        """
        cache_key = self._get_cache_key("activity", days)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        safe_days = max(1, min(days, 90))
        start = datetime.now(timezone.utc) - timedelta(days=safe_days)

        async def fetch_activity_async(table_name: str) -> dict[datetime, int]:
            query = (
                "SELECT date_trunc('day', created_at) AS day, COUNT(*) AS count "
                f"FROM {table_name} "
                "WHERE created_at >= :start "
                "GROUP BY day "
                "ORDER BY day"
            )
            rows = await self._fetch_grouped_async(query, {"start": start})
            return {row["day"]: int(row["count"]) for row in rows}

        # Execute all activity queries in parallel
        (lead_counts, deal_counts, task_counts, note_counts) = await asyncio.gather(
            fetch_activity_async("leads"),
            fetch_activity_async("deals"),
            fetch_activity_async("tasks"),
            fetch_activity_async("notes"),
        )

        days_map: dict[datetime, dict[str, int]] = {}
        for day, count in lead_counts.items():
            days_map.setdefault(day, {})["leads"] = count
        for day, count in deal_counts.items():
            days_map.setdefault(day, {})["deals"] = count
        for day, count in task_counts.items():
            days_map.setdefault(day, {})["tasks"] = count
        for day, count in note_counts.items():
            days_map.setdefault(day, {})["notes"] = count

        series = []
        for day in sorted(days_map.keys()):
            counts = days_map[day]
            series.append(
                {
                    "day": day.date(),
                    "leads": counts.get("leads", 0),
                    "deals": counts.get("deals", 0),
                    "tasks": counts.get("tasks", 0),
                    "notes": counts.get("notes", 0),
                }
            )

        result = {"days": safe_days, "series": series}

        # Cache for 60 seconds
        self._cache.set(cache_key, result, ttl_seconds=60)
        return result
