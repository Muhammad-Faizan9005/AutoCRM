from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.postgres_client import PostgresClient


class AdminOverviewService:
    def __init__(self, db: PostgresClient):
        self.db = db

    def _fetch_scalar(self, query: str, params: dict[str, Any] | None = None) -> Any:
        with self.db.engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            return result.scalar()

    def _fetch_row(self, query: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self.db.engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            row = result.mappings().first()
            return dict(row) if row else None

    async def _fetch_scalar_async(self, query: str, params: dict[str, Any] | None = None) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_scalar, query, params)

    async def _fetch_row_async(self, query: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_row, query, params)

    @staticmethod
    def _format_age(updated_at: datetime | None, now: datetime) -> str:
        if not updated_at:
            return "Updated recently"
        delta = now - updated_at
        hours = int(delta.total_seconds() // 3600)
        if hours < 1:
            return "Updated just now"
        if hours < 24:
            return f"Updated {hours}h ago"
        days = max(1, hours // 24)
        return f"Updated {days}d ago"

    async def get_overview(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        since_24h = now - timedelta(hours=24)
        since_30d = now - timedelta(days=30)

        (
            active_users,
            total_users,
            permissions_changed,
            import_leads,
            import_tickets,
            leads_total,
            deals_total,
            customers_total,
            tasks_total,
            dormant_users,
            invited_users,
            invited_latest,
            latest_permission_update,
        ) = await asyncio.gather(
            self._fetch_scalar_async(
                "SELECT COUNT(*) FROM agents WHERE is_active = true"
            ),
            self._fetch_scalar_async("SELECT COUNT(*) FROM agents"),
            self._fetch_scalar_async(
                "SELECT COUNT(*) FROM agent_permissions WHERE updated_at >= :since",
                {"since": since_24h},
            ),
            self._fetch_scalar_async(
                "SELECT COUNT(*) FROM leads WHERE source = 'import' AND created_at >= :since",
                {"since": since_24h},
            ),
            self._fetch_scalar_async(
                "SELECT COUNT(*) FROM tickets WHERE created_at >= :since",
                {"since": since_24h},
            ),
            self._fetch_scalar_async("SELECT COUNT(*) FROM leads"),
            self._fetch_scalar_async("SELECT COUNT(*) FROM deals"),
            self._fetch_scalar_async("SELECT COUNT(*) FROM customers"),
            self._fetch_scalar_async("SELECT COUNT(*) FROM tasks"),
            self._fetch_scalar_async(
                "SELECT COUNT(*) FROM agents WHERE is_active = true AND updated_at < :since",
                {"since": since_30d},
            ),
            self._fetch_scalar_async(
                "SELECT COUNT(*) FROM agents WHERE status = 'invited'"
            ),
            self._fetch_row_async(
                "SELECT MAX(updated_at) AS updated_at FROM agents WHERE status = 'invited'"
            ),
            self._fetch_row_async(
                """
                SELECT ap.updated_at, a.full_name
                FROM agent_permissions ap
                JOIN agents a ON a.id = ap.user_id
                ORDER BY ap.updated_at DESC
                LIMIT 1
                """,
            ),
        )

        active_users = int(active_users or 0)
        total_users = int(total_users or 0)
        inactive_users = max(0, total_users - active_users)
        permissions_changed = int(permissions_changed or 0)
        import_total = int(import_leads or 0) + int(import_tickets or 0)

        leads_total = int(leads_total or 0)
        deals_total = int(deals_total or 0)
        customers_total = int(customers_total or 0)
        tasks_total = int(tasks_total or 0)

        max_count = max(leads_total, deals_total, customers_total, tasks_total, 0)
        def _percent(value: int) -> int:
            if max_count <= 0:
                return 0
            return int(round((value / max_count) * 100))

        coverage = [
            {"label": "Leads", "percent": _percent(leads_total)},
            {"label": "Deals", "percent": _percent(deals_total)},
            {"label": "Contacts", "percent": _percent(customers_total)},
            {"label": "Tasks", "percent": _percent(tasks_total)},
        ]

        dormant_users = int(dormant_users or 0)
        invited_users = int(invited_users or 0)
        invited_age = self._format_age(
            invited_latest.get("updated_at") if invited_latest else None,
            now,
        )

        activity: list[dict[str, Any]] = []
        if latest_permission_update:
            updated_at = latest_permission_update.get("updated_at")
            full_name = latest_permission_update.get("full_name") or "Unknown user"
            activity.append(
                {
                    "message": f"Permissions updated for {full_name}",
                    "at": updated_at or now,
                }
            )

        highlights = [
            {
                "label": "Active Operators",
                "value": str(active_users),
                "meta": f"{inactive_users} inactive",
            },
            {
                "label": "Permissions Changed",
                "value": str(permissions_changed),
                "meta": "Last 24 hours",
            },
            {
                "label": "Data Imports",
                "value": str(import_total),
                "meta": "Last 24 hours",
            },
        ]

        watchlist = [
            {
                "title": "Dormant accounts",
                "value": f"{dormant_users} users",
                "note": "No profile updates in 30 days",
            }
        ]

        queues = [
            {
                "title": "Access requests",
                "status": f"{invited_users} awaiting approval",
                "age": invited_age,
            }
        ]

        return {
            "highlights": highlights,
            "coverage": coverage,
            "watchlist": watchlist,
            "queues": queues,
            "activity": activity,
        }
