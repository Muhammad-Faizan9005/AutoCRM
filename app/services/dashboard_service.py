from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.postgres_client import PostgresClient


class DashboardService:
    def __init__(self, db: PostgresClient):
        self.db = db

    def _fetch_scalar(self, query: str, params: dict[str, Any] | None = None) -> Any:
        with self.db.engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            return result.scalar()

    def _fetch_grouped(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.db.engine.connect() as conn:
            rows = conn.execute(text(query), params or {}).mappings().all()
        return [dict(row) for row in rows]

    def get_summary(self) -> dict[str, Any]:
        leads_total = int(self._fetch_scalar("SELECT COUNT(*) FROM leads") or 0)
        deals_total = int(self._fetch_scalar("SELECT COUNT(*) FROM deals") or 0)
        organizations_total = int(self._fetch_scalar("SELECT COUNT(*) FROM organizations") or 0)
        tasks_total = int(self._fetch_scalar("SELECT COUNT(*) FROM tasks") or 0)
        notes_total = int(self._fetch_scalar("SELECT COUNT(*) FROM notes") or 0)
        revenue_total = float(self._fetch_scalar("SELECT COALESCE(SUM(value), 0) FROM deals") or 0)

        pipeline = self._fetch_grouped(
            """
            SELECT stage,
                   COUNT(*) AS count,
                   COALESCE(SUM(value), 0) AS value_total
            FROM deals
            GROUP BY stage
            ORDER BY stage
            """
        )
        for row in pipeline:
            row["value_total"] = float(row.get("value_total") or 0)

        leads_by_status = self._fetch_grouped(
            """
            SELECT status, COUNT(*) AS count
            FROM leads
            GROUP BY status
            ORDER BY status
            """
        )

        tasks_by_status = self._fetch_grouped(
            """
            SELECT status, COUNT(*) AS count
            FROM tasks
            GROUP BY status
            ORDER BY status
            """
        )

        return {
            "leads_total": leads_total,
            "deals_total": deals_total,
            "organizations_total": organizations_total,
            "tasks_total": tasks_total,
            "notes_total": notes_total,
            "revenue_total": revenue_total,
            "pipeline": pipeline,
            "leads_by_status": leads_by_status,
            "tasks_by_status": tasks_by_status,
        }

    def get_activity(self, *, days: int = 14) -> dict[str, Any]:
        safe_days = max(1, min(days, 90))
        start = datetime.now(timezone.utc) - timedelta(days=safe_days)

        def fetch_activity(table_name: str) -> dict[datetime, int]:
            query = (
                "SELECT date_trunc('day', created_at) AS day, COUNT(*) AS count "
                f"FROM {table_name} "
                "WHERE created_at >= :start "
                "GROUP BY day "
                "ORDER BY day"
            )
            rows = self._fetch_grouped(query, {"start": start})
            return {row["day"]: int(row["count"]) for row in rows}

        lead_counts = fetch_activity("leads")
        deal_counts = fetch_activity("deals")
        task_counts = fetch_activity("tasks")
        note_counts = fetch_activity("notes")

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
