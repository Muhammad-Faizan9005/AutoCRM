from __future__ import annotations

import hashlib
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.database import run_db_operation
from app.postgres_client import PostgresClient
from app.utils.cache import get_cache


class DashboardService:
    def __init__(self, db: PostgresClient):
        self.db = db
        self._cache = get_cache()

    def _get_cache_key(self, query_type: str, days: int = 0, scope: str = "global") -> str:
        """Generate cache key for dashboard queries."""
        raw_key = f"{query_type}:{days}:{scope}"
        query_hash = hashlib.md5(raw_key.encode()).hexdigest()[:8]
        return f"dashboard:{query_type}:{days}:{scope}:{query_hash}"

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

    def _scope(self, current_user: dict[str, Any]) -> dict[str, str]:
        role = str(current_user.get("role") or "").strip().lower()
        user_id = str(current_user.get("id") or "")
        scope_id = "global" if role == "admin" else f"{role or 'user'}:{user_id}"
        return {"role": role, "user_id": user_id, "scope_id": scope_id}

    def _scope_params(self, scope: dict[str, str]) -> dict[str, Any]:
        return {"scope_user_id": scope["user_id"]} if scope["role"] != "admin" else {}

    def _lead_scope_clause(self, scope: dict[str, str], alias: str = "l") -> str:
        if scope["role"] == "admin":
            return ""
        if scope["role"] in {"manager", "sales_manager"}:
            return (
                f" AND EXISTS ("
                f"SELECT 1 FROM team_members tm "
                f"JOIN teams team_scope ON team_scope.id = tm.team_id "
                f"WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = {alias}.owner_id"
                f") "
            )
        return f" AND {alias}.owner_id = :scope_user_id "

    def _deal_scope_clause(self, scope: dict[str, str], deal_alias: str = "d", lead_alias: str = "l") -> str:
        if scope["role"] == "admin":
            return ""
        if scope["role"] in {"manager", "sales_manager"}:
            return (
                f" AND ("
                f"EXISTS (SELECT 1 FROM team_members tm "
                f"JOIN teams team_scope ON team_scope.id = tm.team_id "
                f"WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = {deal_alias}.owner_id) "
                f"OR EXISTS (SELECT 1 FROM team_members tm "
                f"JOIN teams team_scope ON team_scope.id = tm.team_id "
                f"WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = {lead_alias}.owner_id)"
                f") "
            )
        return f" AND ({deal_alias}.owner_id = :scope_user_id OR {lead_alias}.owner_id = :scope_user_id) "

    def _task_scope_clause(self, scope: dict[str, str], alias: str = "t") -> str:
        if scope["role"] == "admin":
            return ""
        if scope["role"] in {"manager", "sales_manager"}:
            return (
                f" AND EXISTS ("
                f"SELECT 1 FROM team_members tm "
                f"JOIN teams team_scope ON team_scope.id = tm.team_id "
                f"WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = {alias}.assigned_to"
                f") "
            )
        return f" AND {alias}.assigned_to = :scope_user_id "

    def _note_scope_clause(self, scope: dict[str, str], note_alias: str = "n", lead_alias: str = "l") -> str:
        if scope["role"] == "admin":
            return ""
        if scope["role"] in {"manager", "sales_manager"}:
            return (
                f" AND ("
                f"({note_alias}.entity_type = 'lead' AND EXISTS ("
                f"SELECT 1 FROM team_members tm "
                f"JOIN teams team_scope ON team_scope.id = tm.team_id "
                f"WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = {lead_alias}.owner_id"
                f")) OR {note_alias}.author_id = :scope_user_id"
                f") "
            )
        return f" AND (({note_alias}.entity_type = 'lead' AND {lead_alias}.owner_id = :scope_user_id) OR {note_alias}.author_id = :scope_user_id) "

    def _organization_scope_clause(self, scope: dict[str, str], alias: str = "o") -> str:
        if scope["role"] == "admin":
            return ""
        lead_scope = self._lead_scope_clause(scope, "l")
        deal_scope = self._deal_scope_clause(scope, "d", "dl")
        return (
            f" AND ("
            f"EXISTS (SELECT 1 FROM leads l WHERE l.organization_id = {alias}.id {lead_scope}) "
            f"OR EXISTS (SELECT 1 FROM deals d LEFT JOIN leads dl ON dl.id = d.lead_id "
            f"WHERE d.organization_id = {alias}.id {deal_scope})"
            f") "
        )

    def _trend(self, current: float, previous: float) -> dict[str, Any]:
        if previous <= 0:
            value = 100 if current > 0 else 0
        else:
            value = round(((current - previous) / previous) * 100)
        return {
            "direction": "up" if value >= 0 else "down",
            "value": abs(int(value)),
            "current": int(current or 0),
            "previous": int(previous or 0),
        }

    def _period_count(
        self,
        conn,
        base_query: str,
        scope: dict[str, str],
        current_start: datetime,
        previous_start: datetime,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        base_params = {**self._scope_params(scope), **(params or {})}
        query = (
            "SELECT "
            "COUNT(*) FILTER (WHERE created_at >= :current_start) AS current_count, "
            "COUNT(*) FILTER (WHERE created_at >= :previous_start AND created_at < :current_start) AS previous_count "
            f"FROM ({base_query}) scoped_periods"
        )
        row = conn.execute(
            text(query),
            {
                **base_params,
                "current_start": current_start,
                "previous_start": previous_start,
            },
        ).mappings().first()
        return int(row.get("current_count") or 0), int(row.get("previous_count") or 0)

    def _period_sum(
        self,
        conn,
        base_query: str,
        scope: dict[str, str],
        current_start: datetime,
        previous_start: datetime,
        params: dict[str, Any] | None = None,
    ) -> tuple[float, float]:
        base_params = {**self._scope_params(scope), **(params or {})}
        query = (
            "SELECT "
            "COALESCE(SUM(value) FILTER (WHERE created_at >= :current_start), 0) AS current_total, "
            "COALESCE(SUM(value) FILTER (WHERE created_at >= :previous_start AND created_at < :current_start), 0) AS previous_total "
            f"FROM ({base_query}) scoped_periods"
        )
        row = conn.execute(
            text(query),
            {
                **base_params,
                "current_start": current_start,
                "previous_start": previous_start,
            },
        ).mappings().first()
        return float(row.get("current_total") or 0), float(row.get("previous_total") or 0)

    def _get_summary_sync(self, current_user: dict[str, Any], trend_days: int) -> dict[str, Any]:
        scope = self._scope(current_user)
        params = self._scope_params(scope)
        safe_days = max(1, min(trend_days, 90))
        now = datetime.now(timezone.utc)
        current_start = now - timedelta(days=safe_days)
        previous_start = current_start - timedelta(days=safe_days)

        leads_from = f"SELECT l.id, l.created_at FROM leads l WHERE 1=1 {self._lead_scope_clause(scope, 'l')}"
        deals_from = (
            "SELECT d.id, d.created_at, d.value FROM deals d "
            "LEFT JOIN leads l ON l.id = d.lead_id "
            f"WHERE 1=1 {self._deal_scope_clause(scope, 'd', 'l')}"
        )
        organizations_from = (
            "SELECT o.id, o.created_at FROM organizations o "
            f"WHERE 1=1 {self._organization_scope_clause(scope, 'o')}"
        )
        tasks_from = f"SELECT t.id, t.created_at FROM tasks t WHERE 1=1 {self._task_scope_clause(scope, 't')}"

        with self.db.engine.connect() as conn:
            leads_total = self._fetch_scalar_with_conn(
                conn, f"SELECT COUNT(*) FROM leads l WHERE 1=1 {self._lead_scope_clause(scope, 'l')}", params
            )
            deals_total = self._fetch_scalar_with_conn(
                conn,
                "SELECT COUNT(*) FROM deals d LEFT JOIN leads l ON l.id = d.lead_id "
                f"WHERE 1=1 {self._deal_scope_clause(scope, 'd', 'l')}",
                params,
            )
            organizations_total = self._fetch_scalar_with_conn(
                conn,
                f"SELECT COUNT(*) FROM organizations o WHERE 1=1 {self._organization_scope_clause(scope, 'o')}",
                params,
            )
            tasks_total = self._fetch_scalar_with_conn(
                conn, f"SELECT COUNT(*) FROM tasks t WHERE 1=1 {self._task_scope_clause(scope, 't')}", params
            )
            notes_total = self._fetch_scalar_with_conn(
                conn,
                "SELECT COUNT(*) FROM notes n LEFT JOIN leads l ON l.id = n.entity_id AND n.entity_type = 'lead' "
                f"WHERE 1=1 {self._note_scope_clause(scope, 'n', 'l')}",
                params,
            )
            revenue_total = self._fetch_scalar_with_conn(
                conn,
                "SELECT COALESCE(SUM(d.value), 0) FROM deals d LEFT JOIN leads l ON l.id = d.lead_id "
                f"WHERE 1=1 {self._deal_scope_clause(scope, 'd', 'l')}",
                params,
            )
            pipeline = self._fetch_grouped_with_conn(
                conn,
                f"""
                SELECT d.stage AS stage,
                       COUNT(*) AS count,
                       COALESCE(SUM(d.value), 0) AS value_total
                FROM deals d
                LEFT JOIN leads l ON l.id = d.lead_id
                WHERE 1=1 {self._deal_scope_clause(scope, 'd', 'l')}
                GROUP BY d.stage
                ORDER BY d.stage
                """,
                params,
            )
            leads_by_status = self._fetch_grouped_with_conn(
                conn,
                f"""
                SELECT l.status AS status, COUNT(*) AS count
                FROM leads l
                WHERE 1=1 {self._lead_scope_clause(scope, 'l')}
                GROUP BY l.status
                ORDER BY l.status
                """,
                params,
            )
            tasks_by_status = self._fetch_grouped_with_conn(
                conn,
                f"""
                SELECT t.status AS status, COUNT(*) AS count
                FROM tasks t
                WHERE 1=1 {self._task_scope_clause(scope, 't')}
                GROUP BY t.status
                ORDER BY t.status
                """,
                params,
            )

            lead_current, lead_previous = self._period_count(conn, leads_from, scope, current_start, previous_start)
            deal_current, deal_previous = self._period_count(conn, deals_from, scope, current_start, previous_start)
            org_current, org_previous = self._period_count(conn, organizations_from, scope, current_start, previous_start)
            task_current, task_previous = self._period_count(conn, tasks_from, scope, current_start, previous_start)
            revenue_current, revenue_previous = self._period_sum(conn, deals_from, scope, current_start, previous_start)

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
            "trends": {
                "leads": self._trend(lead_current, lead_previous),
                "deals": self._trend(deal_current, deal_previous),
                "organizations": self._trend(org_current, org_previous),
                "tasks": self._trend(task_current, task_previous),
                "revenue": self._trend(revenue_current, revenue_previous),
            },
        }

    def _get_activity_sync(self, current_user: dict[str, Any], days: int) -> dict[str, Any]:
        scope = self._scope(current_user)
        params = self._scope_params(scope)
        safe_days = max(1, min(days, 90))
        start_date = datetime.now(timezone.utc).date() - timedelta(days=safe_days - 1)
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)

        def fetch_activity(conn, query: str) -> dict[date, int]:
            rows = self._fetch_grouped_with_conn(conn, query, {"start": start, **params})
            output: dict[date, int] = {}
            for row in rows:
                day = row["day"]
                if isinstance(day, datetime):
                    day = day.date()
                output[day] = int(row["count"])
            return output

        with self.db.engine.connect() as conn:
            lead_counts = fetch_activity(
                conn,
                f"""
                SELECT date_trunc('day', l.created_at) AS day, COUNT(*) AS count
                FROM leads l
                WHERE l.created_at >= :start {self._lead_scope_clause(scope, 'l')}
                GROUP BY day
                ORDER BY day
                """,
            )
            deal_counts = fetch_activity(
                conn,
                f"""
                SELECT date_trunc('day', d.created_at) AS day, COUNT(*) AS count
                FROM deals d
                LEFT JOIN leads l ON l.id = d.lead_id
                WHERE d.created_at >= :start {self._deal_scope_clause(scope, 'd', 'l')}
                GROUP BY day
                ORDER BY day
                """,
            )
            task_counts = fetch_activity(
                conn,
                f"""
                SELECT date_trunc('day', t.created_at) AS day, COUNT(*) AS count
                FROM tasks t
                WHERE t.created_at >= :start {self._task_scope_clause(scope, 't')}
                GROUP BY day
                ORDER BY day
                """,
            )
            note_counts = fetch_activity(
                conn,
                f"""
                SELECT date_trunc('day', n.created_at) AS day, COUNT(*) AS count
                FROM notes n
                LEFT JOIN leads l ON l.id = n.entity_id AND n.entity_type = 'lead'
                WHERE n.created_at >= :start {self._note_scope_clause(scope, 'n', 'l')}
                GROUP BY day
                ORDER BY day
                """,
            )

        series = []
        for offset in range(safe_days):
            day = start_date + timedelta(days=offset)
            series.append(
                {
                    "day": day,
                    "leads": lead_counts.get(day, 0),
                    "deals": deal_counts.get(day, 0),
                    "tasks": task_counts.get(day, 0),
                    "notes": note_counts.get(day, 0),
                }
            )

        return {"days": safe_days, "series": series}

    async def get_summary(self, current_user: dict[str, Any], *, trend_days: int = 30) -> dict[str, Any]:
        """
        Get dashboard summary with all queries executed in parallel.
        Results are cached for 60 seconds to reduce database load.
        """
        scope = self._scope(current_user)
        safe_days = max(1, min(trend_days, 90))
        cache_key = self._get_cache_key("summary", safe_days, scope["scope_id"])
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result = await run_db_operation(lambda: self._get_summary_sync(current_user, safe_days))

        # Cache for 60 seconds
        self._cache.set(cache_key, result, ttl_seconds=60)
        return result

    async def get_activity(self, current_user: dict[str, Any], *, days: int = 14) -> dict[str, Any]:
        """
        Get activity data with all queries executed in parallel.
        Results are cached for 60 seconds.
        """
        scope = self._scope(current_user)
        cache_key = self._get_cache_key("activity", days, scope["scope_id"])
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result = await run_db_operation(lambda: self._get_activity_sync(current_user, days))

        # Cache for 60 seconds
        self._cache.set(cache_key, result, ttl_seconds=60)
        return result
