from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.postgres_client import PostgresClient
from app.utils.cache import get_cache


# Short-TTL cache for the computed overview payload (analytics, not real-time).
_OVERVIEW_CACHE_PREFIX = "admin_overview:"
_OVERVIEW_CACHE_TTL = 30


OPEN_DEAL_STATES = {
    "prospecting",
    "qualified",
    "qualification",
    "demo_making",
    "proposal",
    "proposal_quotation",
    "negotiation",
    "ready_to_close",
}
WON_DEAL_STATES = {"won", "closed_won"}
DONE_TASK_STATES = {"done", "closed", "completed", "canceled", "cancelled"}


class AdminOverviewService:
    # Class-level so the cache survives across requests (the service is a
    # per-request FastAPI dependency). Column sets are static for the DB schema.
    _column_cache: dict[str, set[str]] = {}

    def __init__(self, db: PostgresClient):
        self.db = db

    @staticmethod
    def _normalize_role(role: str | None) -> str:
        normalized = str(role or "").strip().lower().replace("-", "_").replace(" ", "_")
        if normalized == "manager":
            return "sales_manager"
        if normalized == "agent":
            return "sales_rep"
        return normalized

    def _scope(self, current_user: dict[str, Any]) -> dict[str, str]:
        role = self._normalize_role(current_user.get("role"))
        user_id = str(current_user.get("id") or "")
        return {"role": role, "user_id": user_id}

    def _scope_params(self, scope: dict[str, str]) -> dict[str, Any]:
        return {"scope_user_id": scope["user_id"]} if scope["role"] != "admin" else {}

    def _lead_scope_clause(self, scope: dict[str, str], alias: str = "l") -> str:
        if scope["role"] == "admin":
            return ""
        if scope["role"] == "sales_manager":
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
        if scope["role"] == "sales_manager":
            return (
                f" AND EXISTS (SELECT 1 FROM team_members tm "
                f"JOIN teams team_scope ON team_scope.id = tm.team_id "
                f"WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = {deal_alias}.owner_id) "
            )
        return f" AND {deal_alias}.owner_id = :scope_user_id "

    def _task_scope_clause(self, scope: dict[str, str], alias: str = "t") -> str:
        if scope["role"] == "admin":
            return ""
        if scope["role"] == "sales_manager":
            return (
                f" AND EXISTS ("
                f"SELECT 1 FROM team_members tm "
                f"JOIN teams team_scope ON team_scope.id = tm.team_id "
                f"WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = {alias}.assigned_to"
                f") "
            )
        return f" AND {alias}.assigned_to = :scope_user_id "

    def _user_scope_clause(self, scope: dict[str, str], alias: str = "a") -> str:
        if scope["role"] == "admin":
            return ""
        if scope["role"] == "sales_manager":
            return (
                f" AND ("
                f"{alias}.id = :scope_user_id OR EXISTS ("
                f"SELECT 1 FROM team_members tm "
                f"JOIN teams team_scope ON team_scope.id = tm.team_id "
                f"WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = {alias}.id"
                f")) "
            )
        return f" AND {alias}.id = :scope_user_id "

    @staticmethod
    def _format_age(updated_at: datetime | None, now: datetime) -> str:
        if not updated_at:
            return "No recent updates"
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        delta = now - updated_at
        hours = int(delta.total_seconds() // 3600)
        if hours < 1:
            return "Updated just now"
        if hours < 24:
            return f"Updated {hours}h ago"
        days = max(1, hours // 24)
        return f"Updated {days}d ago"

    @staticmethod
    def _format_money(value: Any) -> str:
        amount = float(value or 0)
        if amount >= 1_000_000:
            return f"${amount / 1_000_000:.1f}M"
        if amount >= 1_000:
            return f"${amount / 1_000:.1f}K"
        return f"${amount:,.0f}"

    @staticmethod
    def _safe_int(value: Any) -> int:
        return int(value or 0)

    def _get_columns(self, conn, table_name: str) -> set[str]:
        # Column sets are static for the process lifetime — cache them so we
        # don't pay an information_schema round-trip (~185–400ms) on every
        # dashboard load against the remote DB.
        cached = self._column_cache.get(table_name)
        if cached is not None:
            return cached
        rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        ).mappings().all()
        columns = {str(row["column_name"]) for row in rows}
        self._column_cache[table_name] = columns
        return columns

    def _get_overview_sync(self, current_user: dict[str, Any], days: int = 30) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        safe_days = max(1, min(days, 90))
        since_7d = now - timedelta(days=7)
        since_30d = now - timedelta(days=safe_days)
        scope = self._scope(current_user)
        params = self._scope_params(scope)

        with self.db.engine.connect() as conn:
            deal_columns = self._get_columns(conn, "deals")
            deal_state_expr = (
                "LOWER(COALESCE(NULLIF(d.status, ''), NULLIF(d.stage, ''), 'prospecting'))"
                if "status" in deal_columns
                else "LOWER(COALESCE(NULLIF(d.stage, ''), 'prospecting'))"
            )
            closed_at_expr = "d.closed_at" if "closed_at" in deal_columns else "d.updated_at"

            # Single pass over `agents` for all user metrics (was 5 separate
            # COUNT queries → 5 round-trips). FILTER + MAX collapse it into one.
            user_summary = conn.execute(
                text(
                    f"""
                    SELECT
                        COUNT(*) FILTER (WHERE a.is_active = true) AS active_users,
                        COUNT(*) AS total_users,
                        COUNT(*) FILTER (WHERE a.status = 'invited') AS invited_users,
                        MAX(a.updated_at) FILTER (WHERE a.status = 'invited') AS invited_latest,
                        COUNT(*) FILTER (WHERE a.is_active = true AND a.updated_at < :since_30d) AS dormant_users
                    FROM agents a
                    WHERE 1=1 {self._user_scope_clause(scope, "a")}
                    """
                ),
                {**params, "since_30d": since_30d},
            ).mappings().first() or {}
            active_users = user_summary.get("active_users")
            total_users = user_summary.get("total_users")
            invited_users = user_summary.get("invited_users")
            invited_latest = {"updated_at": user_summary.get("invited_latest")}
            dormant_users = user_summary.get("dormant_users")

            deal_summary = conn.execute(
                text(
                    f"""
                    SELECT
                        COUNT(*) FILTER (WHERE {deal_state_expr} = ANY(:open_states)) AS open_deals,
                        COUNT(*) FILTER (WHERE {deal_state_expr} = ANY(:won_states)) AS won_deals,
                        COUNT(*) FILTER (WHERE {deal_state_expr} = ANY(:won_states) AND {closed_at_expr} >= :since_30d) AS won_30d,
                        COALESCE(SUM(d.value) FILTER (WHERE {deal_state_expr} = ANY(:open_states)), 0) AS open_value,
                        COALESCE(SUM(d.value) FILTER (WHERE {deal_state_expr} = ANY(:won_states) AND {closed_at_expr} >= :since_30d), 0) AS won_value_30d
                    FROM deals d
                    LEFT JOIN leads l ON l.id = d.lead_id
                    WHERE 1=1 {self._deal_scope_clause(scope, "d", "l")}
                    """
                ),
                {
                    **params,
                    "open_states": list(OPEN_DEAL_STATES),
                    "won_states": list(WON_DEAL_STATES),
                    "since_30d": since_30d,
                },
            ).mappings().first() or {}

            lead_summary = conn.execute(
                text(
                    f"""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE l.created_at >= :since_30d) AS new_30d,
                        COUNT(*) FILTER (WHERE l.owner_id IS NULL) AS unassigned
                    FROM leads l
                    WHERE 1=1 {self._lead_scope_clause(scope, "l")}
                    """
                ),
                {**params, "since_30d": since_30d},
            ).mappings().first() or {}

            task_summary = conn.execute(
                text(
                    f"""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (
                            WHERE t.due_at < :now
                              AND NOT (LOWER(COALESCE(t.status, '')) = ANY(:done_states))
                        ) AS overdue,
                        COUNT(*) FILTER (WHERE t.assigned_to IS NULL) AS unassigned
                    FROM tasks t
                    WHERE 1=1 {self._task_scope_clause(scope, "t")}
                    """
                ),
                {**params, "now": now, "done_states": list(DONE_TASK_STATES)},
            ).mappings().first() or {}

            deal_unassigned = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM deals d
                    LEFT JOIN leads l ON l.id = d.lead_id
                    WHERE d.owner_id IS NULL {self._deal_scope_clause(scope, "d", "l")}
                    """
                ),
                params,
            ).scalar()

            open_tickets = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM tickets
                    WHERE LOWER(COALESCE(status, 'open')) NOT IN ('resolved', 'closed')
                    """
                )
            ).scalar()
            import_leads_7d = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM leads l
                    WHERE LOWER(COALESCE(l.source, '')) = 'import'
                      AND l.created_at >= :since_7d
                      {self._lead_scope_clause(scope, "l")}
                    """
                ),
                {**params, "since_7d": since_7d},
            ).scalar()

            stage_rows = conn.execute(
                text(
                    f"""
                    SELECT COALESCE(NULLIF(d.stage, ''), 'Unstaged') AS label,
                           COUNT(*) AS count,
                           COALESCE(SUM(d.value), 0) AS value
                    FROM deals d
                    LEFT JOIN leads l ON l.id = d.lead_id
                    WHERE 1=1 {self._deal_scope_clause(scope, "d", "l")}
                    GROUP BY COALESCE(NULLIF(d.stage, ''), 'Unstaged')
                    ORDER BY count DESC, label ASC
                    LIMIT 6
                    """
                ),
                params,
            ).mappings().all()

            source_rows = conn.execute(
                text(
                    f"""
                    SELECT COALESCE(NULLIF(l.source, ''), 'Unknown') AS label,
                           COUNT(*) AS count
                    FROM leads l
                    WHERE 1=1 {self._lead_scope_clause(scope, "l")}
                    GROUP BY COALESCE(NULLIF(l.source, ''), 'Unknown')
                    ORDER BY count DESC, label ASC
                    LIMIT 6
                    """
                ),
                params,
            ).mappings().all()

            if scope["role"] == "sales_manager":
                performance_rows = conn.execute(
                    text(
                        f"""
                        SELECT a.full_name AS label,
                               (
                                   SELECT COUNT(*)
                                   FROM leads l
                                   WHERE l.owner_id = a.id
                               ) AS leads,
                               (
                                   SELECT COUNT(*)
                                   FROM deals d
                                   WHERE d.owner_id = a.id
                               ) AS deals,
                               (
                                   SELECT COALESCE(SUM(d.value), 0)
                                   FROM deals d
                                   WHERE d.owner_id = a.id
                                     AND {deal_state_expr} = ANY(:open_states)
                               ) AS pipeline
                        FROM agents a
                        JOIN team_members tm ON tm.agent_id = a.id
                        JOIN teams team_scope ON team_scope.id = tm.team_id
                        WHERE team_scope.manager_id = :scope_user_id
                          AND a.is_active = true
                        ORDER BY pipeline DESC, deals DESC, leads DESC
                        LIMIT 5
                        """
                    ),
                    {"scope_user_id": scope["user_id"], "open_states": list(OPEN_DEAL_STATES)},
                ).mappings().all()
            else:
                performance_rows = conn.execute(
                    text(
                        f"""
                        SELECT team_scope.name AS label,
                               (
                                   SELECT COUNT(*)
                                   FROM leads l
                                   JOIN team_members lead_tm ON lead_tm.agent_id = l.owner_id
                                   WHERE lead_tm.team_id = team_scope.id
                               ) AS leads,
                               (
                                   SELECT COUNT(*)
                                   FROM deals d
                                   JOIN team_members deal_tm ON deal_tm.agent_id = d.owner_id
                                   WHERE deal_tm.team_id = team_scope.id
                               ) AS deals,
                               (
                                   SELECT COALESCE(SUM(d.value), 0)
                                   FROM deals d
                                   JOIN team_members deal_tm ON deal_tm.agent_id = d.owner_id
                                   WHERE deal_tm.team_id = team_scope.id
                                     AND {deal_state_expr} = ANY(:open_states)
                               ) AS pipeline
                        FROM teams team_scope
                        ORDER BY pipeline DESC, deals DESC, leads DESC
                        LIMIT 5
                        """
                    ),
                    {"open_states": list(OPEN_DEAL_STATES)},
                ).mappings().all()

            stale_deals = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM deals d
                    LEFT JOIN leads l ON l.id = d.lead_id
                    WHERE {deal_state_expr} = ANY(:open_states)
                      AND d.updated_at < :since_30d
                      {self._deal_scope_clause(scope, "d", "l")}
                    """
                ),
                {**params, "open_states": list(OPEN_DEAL_STATES), "since_30d": since_30d},
            ).scalar()

            activity_rows = conn.execute(
                text(
                    f"""
                    SELECT message, at
                    FROM (
                        SELECT 'New lead: ' || COALESCE(NULLIF(l.name, ''), NULLIF(l.email, ''), 'Lead') AS message,
                               l.created_at AS at
                        FROM leads l
                        WHERE 1=1 {self._lead_scope_clause(scope, "l")}
                        UNION ALL
                        SELECT 'Deal updated: ' || COALESCE(NULLIF(d.stage, ''), 'pipeline') AS message,
                               d.updated_at AS at
                        FROM deals d
                        LEFT JOIN leads l ON l.id = d.lead_id
                        WHERE 1=1 {self._deal_scope_clause(scope, "d", "l")}
                        UNION ALL
                        SELECT 'Task updated: ' || COALESCE(NULLIF(t.title, ''), 'Task') AS message,
                               t.updated_at AS at
                        FROM tasks t
                        WHERE 1=1 {self._task_scope_clause(scope, "t")}
                    ) events
                    WHERE at IS NOT NULL
                    ORDER BY at DESC
                    LIMIT 6
                    """
                ),
                params,
            ).mappings().all()

        active_users = self._safe_int(active_users)
        total_users = self._safe_int(total_users)
        inactive_users = max(0, total_users - active_users)
        open_deals = self._safe_int(deal_summary.get("open_deals"))
        won_30d = self._safe_int(deal_summary.get("won_30d"))
        new_leads_30d = self._safe_int(lead_summary.get("new_30d"))
        overdue_tasks = self._safe_int(task_summary.get("overdue"))
        unassigned_records = (
            self._safe_int(lead_summary.get("unassigned"))
            + self._safe_int(deal_unassigned)
            + self._safe_int(task_summary.get("unassigned"))
        )

        max_stage_count = max([self._safe_int(row.get("count")) for row in stage_rows] + [0])
        max_source_count = max([self._safe_int(row.get("count")) for row in source_rows] + [0])

        def percent(value: int, max_value: int) -> int:
            if max_value <= 0:
                return 0
            return int(round((value / max_value) * 100))

        coverage = [
            {
                "label": str(row.get("label") or "Unstaged").replace("_", " ").title(),
                "percent": percent(self._safe_int(row.get("count")), max_stage_count),
                "value": str(self._safe_int(row.get("count"))),
                "meta": self._format_money(row.get("value")),
            }
            for row in stage_rows
        ]
        sources = [
            {
                "label": str(row.get("label") or "Unknown").replace("_", " ").title(),
                "percent": percent(self._safe_int(row.get("count")), max_source_count),
                "value": str(self._safe_int(row.get("count"))),
                "meta": "leads",
            }
            for row in source_rows
        ]

        highlights = [
            {
                "label": "Open Pipeline",
                "value": self._format_money(deal_summary.get("open_value")),
                "meta": f"{open_deals} open deals",
            },
            {
                "label": "Won Revenue",
                "value": self._format_money(deal_summary.get("won_value_30d")),
                "meta": f"{won_30d} won in {safe_days} days",
            },
            {
                "label": "New Leads",
                "value": new_leads_30d,
                "meta": f"Last {safe_days} days",
            },
            {
                "label": "Overdue Tasks",
                "value": overdue_tasks,
                "meta": f"{self._safe_int(task_summary.get('total'))} total tasks",
            },
            {
                "label": "Active Operators",
                "value": active_users,
                "meta": f"{inactive_users} inactive",
            },
            {
                "label": "Unassigned Records",
                "value": unassigned_records,
                "meta": "Leads, deals, and tasks",
            },
        ]

        watchlist = [
            {
                "title": "Stale open deals",
                "value": f"{self._safe_int(stale_deals)} deals",
                "note": f"No updates in {safe_days} days",
            },
            {
                "title": "Overdue work",
                "value": f"{overdue_tasks} tasks",
                "note": "Past due and not complete",
            },
            {
                "title": "Unassigned records",
                "value": f"{unassigned_records} records",
                "note": "Need owners or assignees",
            },
            {
                "title": "Dormant accounts",
                "value": f"{self._safe_int(dormant_users)} users",
                "note": f"No profile updates in {safe_days} days",
            },
        ]

        invited_age = self._format_age(
            invited_latest.get("updated_at") if invited_latest else None,
            now,
        )
        queues = [
            {
                "title": "Access requests",
                "status": f"{self._safe_int(invited_users)} invited users",
                "age": invited_age,
            },
            {
                "title": "Recent imports",
                "status": f"{self._safe_int(import_leads_7d)} imported leads",
                "age": "Last 7 days",
            },
            {
                "title": "Support queue",
                "status": f"{self._safe_int(open_tickets)} open tickets",
                "age": "Live CRM data",
            },
        ]

        team_performance = [
            {
                "label": str(row.get("label") or "Unnamed team"),
                "value": self._format_money(row.get("pipeline")),
                "meta": f"{self._safe_int(row.get('deals'))} deals / {self._safe_int(row.get('leads'))} leads",
            }
            for row in performance_rows
        ]

        return {
            "highlights": highlights,
            "coverage": coverage,
            "sources": sources,
            "watchlist": watchlist,
            "queues": queues,
            "team_performance": team_performance,
            "activity": [dict(row) for row in activity_rows],
        }

    async def get_overview(self, current_user: dict[str, Any], days: int = 30) -> dict[str, Any]:
        # Short-TTL cache of the whole payload per (user, days). The dashboard is
        # analytics, not real-time, so a ~30s cache lets repeat loads / multiple
        # widgets return instantly (0 round-trips) instead of re-running the full
        # query set against the remote DB every time.
        cache = get_cache()
        user_id = str(current_user.get("id") or "")
        role = str(current_user.get("role") or "")
        cache_key = f"{_OVERVIEW_CACHE_PREFIX}{user_id}:{role}:{days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._get_overview_sync, current_user, days)
        cache.set(cache_key, result, ttl_seconds=_OVERVIEW_CACHE_TTL)
        return result
