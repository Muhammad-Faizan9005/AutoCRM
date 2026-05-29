from __future__ import annotations

from sqlalchemy import text
from supabase import Client

from app.database import run_db_operation


def _is_admin_role(role: str | None) -> bool:
    return str(role or "").strip().lower() == "admin"


def _is_manager_role(role: str | None) -> bool:
    return str(role or "").strip().lower() in {"manager", "sales_manager"}


async def is_manager_of_rep(db: Client, manager_id: str, rep_id: str) -> bool:
    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM team_members tm "
                    "JOIN teams t ON t.id = tm.team_id "
                    "WHERE t.manager_id = :mid AND tm.agent_id = :rid LIMIT 1"
                ),
                {"mid": manager_id, "rid": rep_id},
            ).first()
            return bool(row)

    return await run_db_operation(_query)


async def get_lead_owner_id(db: Client, lead_id: str) -> str | None:
    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT owner_id FROM leads WHERE id = :lead_id"),
                {"lead_id": lead_id},
            ).mappings().first()
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

    if user_id == rep_id:
        return True

    if _is_manager_role(current_user.get("role")):
        return await is_manager_of_rep(db, user_id, rep_id)

    return False
