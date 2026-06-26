from __future__ import annotations

from typing import Any

from sqlalchemy import text
from supabase import Client

from app.database import run_db_operation


def _is_admin_role(role: str | None) -> bool:
    return str(role or "").strip().lower() == "admin"


def _is_manager_role(role: str | None) -> bool:
    return str(role or "").strip().lower() in {"manager", "sales_manager"}


async def is_manager_of_rep(db: Client, manager_id: str, rep_id: str) -> bool:
    if not manager_id or not rep_id:
        return False

    def _query():
        engine = getattr(db, "engine", None)
        if engine is not None:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT 1 FROM team_members tm "
                        "JOIN teams t ON t.id = tm.team_id "
                        "WHERE t.manager_id = :mid AND tm.agent_id = :rid LIMIT 1"
                    ),
                    {"mid": manager_id, "rid": rep_id},
                ).first()
                return bool(row)

        teams = db.table("teams").select("*").eq("manager_id", manager_id).execute().data or []
        team_ids = {str(team.get("id")) for team in teams}
        if not team_ids:
            return False

        memberships = db.table("team_members").select("*").eq("agent_id", rep_id).execute().data or []
        return any(str(member.get("team_id")) in team_ids for member in memberships)

    return await run_db_operation(_query)


async def get_agent_team_id(db: Client, agent_id: str | None) -> str | None:
    if not agent_id:
        return None

    def _query():
        engine = getattr(db, "engine", None)
        if engine is not None:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT COALESCE(a.team_id, tm.team_id) AS team_id "
                        "FROM agents a "
                        "LEFT JOIN team_members tm ON tm.agent_id = a.id "
                        "WHERE a.id = :agent_id LIMIT 1"
                    ),
                    {"agent_id": agent_id},
                ).mappings().first()
                return str(row.get("team_id")) if row and row.get("team_id") else None

        rows = db.table("agents").select("*").eq("id", agent_id).limit(1).execute().data or []
        agent = rows[0] if rows else None
        if agent and agent.get("team_id"):
            return str(agent.get("team_id"))
        memberships = db.table("team_members").select("*").eq("agent_id", agent_id).limit(1).execute().data or []
        membership = memberships[0] if memberships else None
        return str(membership.get("team_id")) if membership and membership.get("team_id") else None

    return await run_db_operation(_query)


async def is_manager_of_team(db: Client, manager_id: str, team_id: str | None) -> bool:
    if not manager_id or not team_id:
        return False

    def _query():
        engine = getattr(db, "engine", None)
        if engine is not None:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT 1 FROM teams WHERE id = :team_id AND manager_id = :manager_id LIMIT 1"),
                    {"team_id": team_id, "manager_id": manager_id},
                ).first()
                return bool(row)

        rows = db.table("teams").select("*").eq("id", team_id).eq("manager_id", manager_id).limit(1).execute().data or []
        return bool(rows)

    return await run_db_operation(_query)


async def can_access_owned_record(
    db: Client,
    current_user: dict[str, Any],
    *,
    owner_id: str | None,
    team_id: str | None = None,
) -> bool:
    user_id = str(current_user.get("id") or "")
    if not user_id:
        return False

    role = str(current_user.get("role") or "").strip().lower()
    if _is_admin_role(role):
        return True

    if owner_id and str(owner_id) == user_id:
        return True

    if _is_manager_role(role):
        if owner_id and await is_manager_of_rep(db, user_id, str(owner_id)):
            return True
        if team_id and await is_manager_of_team(db, user_id, str(team_id)):
            return True
        return False

    return False


async def can_access_organization_record(
    db: Client,
    current_user: dict[str, Any],
    *,
    organization_id: str,
    owner_id: str | None,
    team_id: str | None = None,
) -> bool:
    if await can_access_owned_record(db, current_user, owner_id=owner_id, team_id=team_id):
        return True

    user_id = str(current_user.get("id") or "")
    if not user_id:
        return False

    role = str(current_user.get("role") or "").strip().lower()
    if _is_admin_role(role):
        return True

    def _query():
        engine = getattr(db, "engine", None)
        if engine is not None:
            with engine.connect() as conn:
                if _is_manager_role(role):
                    row = conn.execute(
                        text(
                            "SELECT 1 FROM leads l "
                            "LEFT JOIN team_members tm ON tm.agent_id = l.owner_id "
                            "LEFT JOIN teams t ON t.id = tm.team_id "
                            "WHERE l.organization_id = :organization_id "
                            "AND (l.owner_id = :user_id OR t.manager_id = :user_id) "
                            "LIMIT 1"
                        ),
                        {"organization_id": organization_id, "user_id": user_id},
                    ).first()
                else:
                    row = conn.execute(
                        text(
                            "SELECT 1 FROM leads l "
                            "WHERE l.organization_id = :organization_id "
                            "AND l.owner_id = :user_id "
                            "LIMIT 1"
                        ),
                        {"organization_id": organization_id, "user_id": user_id},
                    ).first()
                return bool(row)

        tables = getattr(db, "tables", {})
        if _is_manager_role(role):
            team_ids = {str(team.get("id")) for team in tables.get("teams", []) if str(team.get("manager_id")) == user_id}
            member_ids = {
                str(member.get("agent_id"))
                for member in tables.get("team_members", [])
                if str(member.get("team_id")) in team_ids
            }
            return any(
                str(lead.get("organization_id") or "") == organization_id
                and str(lead.get("owner_id") or "") in {user_id, *member_ids}
                for lead in tables.get("leads", [])
            )

        return any(
            str(lead.get("organization_id") or "") == organization_id
            and str(lead.get("owner_id") or "") == user_id
            for lead in tables.get("leads", [])
        )

    return await run_db_operation(_query)


async def can_access_customer_record(
    db: Client,
    current_user: dict[str, Any],
    *,
    customer_id: str,
    owner_id: str | None,
    team_id: str | None = None,
) -> bool:
    if await can_access_owned_record(db, current_user, owner_id=owner_id, team_id=team_id):
        return True

    user_id = str(current_user.get("id") or "")
    if not user_id:
        return False

    role = str(current_user.get("role") or "").strip().lower()
    if _is_admin_role(role):
        return True

    def _query():
        engine = getattr(db, "engine", None)
        if engine is not None:
            with engine.connect() as conn:
                if _is_manager_role(role):
                    row = conn.execute(
                        text(
                            "SELECT 1 FROM deals d "
                            "LEFT JOIN leads l ON l.id = d.lead_id "
                            "LEFT JOIN team_members deal_tm ON deal_tm.agent_id = d.owner_id "
                            "LEFT JOIN teams deal_team ON deal_team.id = deal_tm.team_id "
                            "LEFT JOIN team_members lead_tm ON lead_tm.agent_id = l.owner_id "
                            "LEFT JOIN teams lead_team ON lead_team.id = lead_tm.team_id "
                            "WHERE d.customer_id = :customer_id "
                            "AND (d.owner_id = :user_id OR l.owner_id = :user_id "
                            "OR deal_team.manager_id = :user_id OR lead_team.manager_id = :user_id) "
                            "LIMIT 1"
                        ),
                        {"customer_id": customer_id, "user_id": user_id},
                    ).first()
                else:
                    row = conn.execute(
                        text(
                            "SELECT 1 FROM deals d "
                            "LEFT JOIN leads l ON l.id = d.lead_id "
                            "WHERE d.customer_id = :customer_id "
                            "AND (d.owner_id = :user_id OR l.owner_id = :user_id) "
                            "LIMIT 1"
                        ),
                        {"customer_id": customer_id, "user_id": user_id},
                    ).first()
                return bool(row)

        tables = getattr(db, "tables", {})
        leads_by_id = {str(lead.get("id")): lead for lead in tables.get("leads", [])}
        if _is_manager_role(role):
            team_ids = {str(team.get("id")) for team in tables.get("teams", []) if str(team.get("manager_id")) == user_id}
            member_ids = {
                str(member.get("agent_id"))
                for member in tables.get("team_members", [])
                if str(member.get("team_id")) in team_ids
            }
            visible_owner_ids = {user_id, *member_ids}
            return any(
                str(deal.get("customer_id") or "") == customer_id
                and (
                    str(deal.get("owner_id") or "") in visible_owner_ids
                    or str(leads_by_id.get(str(deal.get("lead_id") or ""), {}).get("owner_id") or "") in visible_owner_ids
                )
                for deal in tables.get("deals", [])
            )

        return any(
            str(deal.get("customer_id") or "") == customer_id
            and (
                str(deal.get("owner_id") or "") == user_id
                or str(leads_by_id.get(str(deal.get("lead_id") or ""), {}).get("owner_id") or "") == user_id
            )
            for deal in tables.get("deals", [])
        )

    return await run_db_operation(_query)


async def can_assign_owned_record(
    db: Client,
    current_user: dict[str, Any],
    *,
    owner_id: str | None,
    team_id: str | None = None,
) -> bool:
    user_id = str(current_user.get("id") or "")
    if not user_id:
        return False

    role = str(current_user.get("role") or "").strip().lower()
    if _is_admin_role(role):
        return True

    if owner_id and str(owner_id) == user_id:
        return True

    if _is_manager_role(role):
        if owner_id:
            return await is_manager_of_rep(db, user_id, str(owner_id))
        if team_id:
            return await is_manager_of_team(db, user_id, str(team_id))
        return True

    return False


async def get_lead_owner_id(db: Client, lead_id: str) -> str | None:
    def _query():
        engine = getattr(db, "engine", None)
        if engine is not None:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT owner_id FROM leads WHERE id = :lead_id"),
                    {"lead_id": lead_id},
                ).mappings().first()
                return str(row.get("owner_id")) if row and row.get("owner_id") else None

        rows = db.table("leads").select("*").eq("id", lead_id).limit(1).execute().data or []
        row = rows[0] if rows else None
        return str(row.get("owner_id")) if row and row.get("owner_id") else None

    return await run_db_operation(_query)


async def can_access_lead(db: Client, current_user: dict, lead_id: str) -> bool:
    user_id = str(current_user.get("id") or "")
    if not user_id:
        return False

    if _is_admin_role(current_user.get("role")):
        return True

    owner_id = await get_lead_owner_id(db, lead_id)
    if not owner_id:
        return False
    if owner_id == user_id:
        return True

    if _is_manager_role(current_user.get("role")):
        return await is_manager_of_rep(db, user_id, owner_id)

    return False


async def can_access_rep(db: Client, current_user: dict, rep_id: str) -> bool:
    user_id = str(current_user.get("id") or "")
    if not user_id:
        return False

    if _is_admin_role(current_user.get("role")):
        return True

    if not rep_id:
        return _is_manager_role(current_user.get("role"))

    if user_id == rep_id:
        return True

    if _is_manager_role(current_user.get("role")):
        return await is_manager_of_rep(db, user_id, rep_id)

    return False
