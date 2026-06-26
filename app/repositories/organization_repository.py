from __future__ import annotations

from typing import Any

from sqlalchemy import text
from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository):
    def __init__(self, db: Client):
        super().__init__(db=db, table_name="organizations", resource_name="Organization")

    async def list_organizations(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        industry: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            query = self.db.table(self.table_name).select("*")
            if industry:
                query = query.eq("industry", industry)
            if search:
                query = query.ilike("name", f"%{search}%")

            query = query.order("created_at", desc=True).range(skip, skip + limit - 1)
            response = await run_db_operation(lambda: query.execute())
        except Exception as exc:
            raise DatabaseError(detail="Failed to list organizations") from exc

        return response.data or []

    async def list_organizations_for_user(
        self,
        *,
        current_user: dict[str, Any],
        skip: int = 0,
        limit: int = 100,
        industry: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        role = str(current_user.get("role") or "").strip().lower()
        user_id = str(current_user.get("id") or "")
        if not user_id:
            return []

        engine = getattr(self.db, "engine", None)
        if engine is None:
            rows = await self.list_organizations(skip=0, limit=10000, industry=industry, search=search)
            return self._filter_rows_for_user(rows, current_user)[skip : skip + limit]

        try:
            def _query():
                sql = "SELECT o.* FROM organizations o WHERE 1=1 "
                params: dict[str, Any] = {}
                if industry:
                    sql += "AND o.industry = :industry "
                    params["industry"] = industry
                if search:
                    sql += "AND o.name ILIKE :search "
                    params["search"] = f"%{search}%"

                if role != "admin":
                    params["scope_user_id"] = user_id
                    if role in {"manager", "sales_manager"}:
                        sql += (
                            "AND (o.owner_id = :scope_user_id "
                            "OR EXISTS ("
                            "SELECT 1 FROM team_members tm "
                            "JOIN teams t ON t.id = tm.team_id "
                            "WHERE t.manager_id = :scope_user_id AND tm.agent_id = o.owner_id"
                            ") "
                            "OR EXISTS ("
                            "SELECT 1 FROM teams team_scope "
                            "WHERE team_scope.manager_id = :scope_user_id AND team_scope.id = o.team_id"
                            ") "
                            "OR EXISTS ("
                            "SELECT 1 FROM leads l "
                            "LEFT JOIN team_members lead_tm ON lead_tm.agent_id = l.owner_id "
                            "LEFT JOIN teams lead_team ON lead_team.id = lead_tm.team_id "
                            "WHERE l.organization_id = o.id "
                            "AND (l.owner_id = :scope_user_id OR lead_team.manager_id = :scope_user_id)"
                            ")) "
                        )
                    else:
                        sql += (
                            "AND (o.owner_id = :scope_user_id "
                            "OR EXISTS ("
                            "SELECT 1 FROM leads l "
                            "WHERE l.organization_id = o.id AND l.owner_id = :scope_user_id"
                            ")) "
                        )

                sql += "ORDER BY o.created_at DESC OFFSET :skip LIMIT :limit"
                params["skip"] = skip
                params["limit"] = limit
                with engine.connect() as conn:
                    rows = conn.execute(text(sql), params).mappings().all()
                    return [dict(row) for row in rows]

            return await run_db_operation(_query)
        except Exception as exc:
            raise DatabaseError(detail="Failed to list organizations") from exc

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
            return [
                row
                for row in rows
                if str(row.get("owner_id") or "") in {user_id, *member_ids}
                or str(row.get("team_id") or "") in team_ids
                or any(
                    str(lead.get("organization_id") or "") == str(row.get("id"))
                    and str(lead.get("owner_id") or "") in {user_id, *member_ids}
                    for lead in tables.get("leads", [])
                )
            ]
        tables = getattr(self.db, "tables", {})
        return [
            row
            for row in rows
            if str(row.get("owner_id") or "") == user_id
            or any(
                str(lead.get("organization_id") or "") == str(row.get("id"))
                and str(lead.get("owner_id") or "") == user_id
                for lead in tables.get("leads", [])
            )
        ]
