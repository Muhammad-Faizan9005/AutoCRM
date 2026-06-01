from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.database import run_db_operation
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

    def _fetch_scalar_with_conn(
        self, conn, query: str, params: dict[str, Any] | None = None
    ) -> Any:
        result = conn.execute(text(query), params or {})
        return result.scalar()

    def _fetch_grouped_with_conn(
        self, conn, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        rows = conn.execute(text(query), params or {}).mappings().all()
        return [dict(row) for row in rows]

    def _get_summary_sync(self) -> dict[str, Any]:
        with self.db.engine.connect() as conn:
            leads_total = self._fetch_scalar_with_conn(conn, "SELECT COUNT(*) FROM leads")
            deals_total = self._fetch_scalar_with_conn(conn, "SELECT COUNT(*) FROM deals")
            organizations_total = self._fetch_scalar_with_conn(conn, "SELECT COUNT(*) FROM organizations")
            tasks_total = self._fetch_scalar_with_conn(conn, "SELECT COUNT(*) FROM tasks")
            notes_total = self._fetch_scalar_with_conn(conn, "SELECT COUNT(*) FROM notes")
            revenue_total = self._fetch_scalar_with_conn(
                conn, "SELECT COALESCE(SUM(value), 0) FROM deals"
            )
            pipeline = self._fetch_grouped_with_conn(
                conn,
                """
                SELECT stage,
                       COUNT(*) AS count,
                       COALESCE(SUM(value), 0) AS value_total
                FROM deals
                GROUP BY stage
                ORDER BY stage
                """,
            )
            leads_by_status = self._fetch_grouped_with_conn(
                conn,
                """
                SELECT status, COUNT(*) AS count
                FROM leads
                GROUP BY status
                ORDER BY status
                """,
            )
            tasks_by_status = self._fetch_grouped_with_conn(
                conn,
                """
                SELECT status, COUNT(*) AS count
                FROM tasks
                GROUP BY status
                ORDER BY status
                """,
            )

        for row in pipeline:
            row["value_total"] = float(row.get("value_total") or 0)

        return {
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

    def _get_activity_sync(self, days: int) -> dict[str, Any]:
        safe_days = max(1, min(days, 90))
        start = datetime.now(timezone.utc) - timedelta(days=safe_days)

        def fetch_activity(conn, table_name: str) -> dict[datetime, int]:
            query = (
                "SELECT date_trunc('day', created_at) AS day, COUNT(*) AS count "
                f"FROM {table_name} "
                "WHERE created_at >= :start "
                "GROUP BY day "
                "ORDER BY day"
            )
            rows = self._fetch_grouped_with_conn(conn, query, {"start": start})
            return {row["day"]: int(row["count"]) for row in rows}

        with self.db.engine.connect() as conn:
            lead_counts = fetch_activity(conn, "leads")
            deal_counts = fetch_activity(conn, "deals")
            task_counts = fetch_activity(conn, "tasks")
            note_counts = fetch_activity(conn, "notes")

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

        return {"days": safe_days, "series": series}

    async def get_summary(self) -> dict[str, Any]:
        """
        Get dashboard summary with all queries executed in parallel.
        Results are cached for 60 seconds to reduce database load.
        """
        cache_key = self._get_cache_key("summary")
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result = await run_db_operation(self._get_summary_sync)

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

        result = await run_db_operation(lambda: self._get_activity_sync(days))

        # Cache for 60 seconds
        self._cache.set(cache_key, result, ttl_seconds=60)
        return result
