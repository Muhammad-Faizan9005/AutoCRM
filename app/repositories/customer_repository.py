from __future__ import annotations

from typing import Any

from sqlalchemy import text
from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError
from app.repositories.base import BaseRepository


class CustomerRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="customers", resource_name="Customer")

    async def list_customers(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = {"status": status} if status else None
        return await self.list(skip=skip, limit=limit, filters=filters)

    async def list_customers_for_user(
        self,
        *,
        current_user: dict[str, Any],
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        role = str(current_user.get("role") or "").strip().lower()
        user_id = str(current_user.get("id") or "")
        if not user_id:
            return []

        engine = getattr(self.db, "engine", None)
        if engine is None:
            rows = await self.list_customers(skip=0, limit=10000, status=status)
            return self._filter_rows_for_user(rows, current_user)[skip : skip + limit]

        try:
            def _query():
                sql = "SELECT c.* FROM customers c WHERE 1=1 "
                params: dict[str, Any] = {}
                if status:
                    sql += "AND c.status = :status "
                    params["status"] = status

                if role != "admin":
                    params["scope_user_id"] = user_id
                    if role in {"manager", "sales_manager"}:
                        sql += (
                            "AND (c.owner_id = :scope_user_id "
                            "OR EXISTS ("
                            "SELECT 1 FROM team_members tm "
                            "JOIN teams t ON t.id = tm.team_id "
                            "WHERE t.manager_id = :scope_user_id AND tm.agent_id = c.owner_id"
                            ") "
                            "OR EXISTS ("
                            "SELECT 1 FROM teams team_scope "
                            "WHERE team_scope.manager_id = :scope_user_id AND team_scope.id = c.team_id"
                            ") "
                            "OR EXISTS ("
                            "SELECT 1 FROM deals d "
                            "LEFT JOIN leads l ON l.id = d.lead_id "
                            "LEFT JOIN team_members deal_tm ON deal_tm.agent_id = d.owner_id "
                            "LEFT JOIN teams deal_team ON deal_team.id = deal_tm.team_id "
                            "LEFT JOIN team_members lead_tm ON lead_tm.agent_id = l.owner_id "
                            "LEFT JOIN teams lead_team ON lead_team.id = lead_tm.team_id "
                            "WHERE d.customer_id = c.id "
                            "AND (d.owner_id = :scope_user_id OR l.owner_id = :scope_user_id "
                            "OR deal_team.manager_id = :scope_user_id OR lead_team.manager_id = :scope_user_id)"
                            ")) "
                        )
                    else:
                        sql += (
                            "AND (c.owner_id = :scope_user_id "
                            "OR EXISTS ("
                            "SELECT 1 FROM deals d "
                            "LEFT JOIN leads l ON l.id = d.lead_id "
                            "WHERE d.customer_id = c.id "
                            "AND (d.owner_id = :scope_user_id OR l.owner_id = :scope_user_id)"
                            ")) "
                        )

                sql += "ORDER BY c.created_at DESC OFFSET :skip LIMIT :limit"
                params["skip"] = skip
                params["limit"] = limit
                with engine.connect() as conn:
                    rows = conn.execute(text(sql), params).mappings().all()
                    return [dict(row) for row in rows]

            return await run_db_operation(_query)
        except Exception as exc:
            raise DatabaseError(detail="Failed to list customers") from exc

    def _filter_rows_for_user(self, rows: list[dict[str, Any]], current_user: dict[str, Any]) -> list[dict[str, Any]]:
        role = str(current_user.get("role") or "").strip().lower()
        user_id = str(current_user.get("id") or "")
        if role == "admin":
            return rows
        if role in {"manager", "sales_manager"}:
            tables = getattr(self.db, "tables", {})
            team_ids = {str(team.get("id")) for team in tables.get("teams", []) if str(team.get("manager_id")) == user_id}
            member_ids = {
                str(member.get("agent_id"))
                for member in tables.get("team_members", [])
                if str(member.get("team_id")) in team_ids
            }
            leads_by_id = {str(lead.get("id")): lead for lead in tables.get("leads", [])}
            visible_owner_ids = {user_id, *member_ids}
            return [
                row
                for row in rows
                if str(row.get("owner_id") or "") in {user_id, *member_ids}
                or str(row.get("team_id") or "") in team_ids
                or any(
                    str(deal.get("customer_id") or "") == str(row.get("id"))
                    and (
                        str(deal.get("owner_id") or "") in visible_owner_ids
                        or str(leads_by_id.get(str(deal.get("lead_id") or ""), {}).get("owner_id") or "") in visible_owner_ids
                    )
                    for deal in tables.get("deals", [])
                )
            ]
        tables = getattr(self.db, "tables", {})
        leads_by_id = {str(lead.get("id")): lead for lead in tables.get("leads", [])}
        return [
            row
            for row in rows
            if str(row.get("owner_id") or "") == user_id
            or any(
                str(deal.get("customer_id") or "") == str(row.get("id"))
                and (
                    str(deal.get("owner_id") or "") == user_id
                    or str(leads_by_id.get(str(deal.get("lead_id") or ""), {}).get("owner_id") or "") == user_id
                )
                for deal in tables.get("deals", [])
            )
        ]
