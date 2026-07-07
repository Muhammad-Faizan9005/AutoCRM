from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.postgres_client import PostgresClient


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
        return {str(row["column_name"]) for row in rows}

    def _get_overview_sync(self, current_user: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        since_7d = now - timedelta(days=7)
        since_30d = now - timedelta(days=30)
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

            active_users = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM agents a
                    WHERE a.is_active = true {self._user_scope_clause(scope, "a")}
                    """
                ),
                params,
            ).scalar()
            total_users = conn.execute(
                text(f"SELECT COUNT(*) FROM agents a WHERE 1=1 {self._user_scope_clause(scope, 'a')}"),
                params,
            ).scalar()
            invited_users = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM agents a
                    WHERE a.status = 'invited' {self._user_scope_clause(scope, "a")}
                    """
                ),
                params,
            ).scalar()
            invited_latest = conn.execute(
                text(
                    f"""
                    SELECT MAX(a.updated_at) AS updated_at
                    FROM agents a
                    WHERE a.status = 'invited' {self._user_scope_clause(scope, "a")}
                    """
                ),
                params,
            ).mappings().first()
            dormant_users = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM agents a
                    WHERE a.is_active = true
                      AND a.updated_at < :since_30d
                      {self._user_scope_clause(scope, "a")}
                    """
                ),
                {**params, "since_30d": since_30d},
            ).scalar()

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
                "meta": f"{won_30d} won in 30 days",
            },
            {
                "label": "New Leads",
                "value": new_leads_30d,
                "meta": "Last 30 days",
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
                "note": "No updates in 30 days",
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
                "note": "No profile updates in 30 days",
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

    async def get_overview(self, current_user: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_overview_sync, current_user)
