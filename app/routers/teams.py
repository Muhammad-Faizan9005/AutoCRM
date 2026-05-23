from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text

from app.auth.dependencies import require_permissions
from app.database import get_db, run_db_operation
from app.postgres_client import PostgresClient
from app.schemas.teams import (
    TeamCreate,
    TeamDetail,
    TeamList,
    TeamMemberAdd,
    TeamMemberStats,
    TeamResponse,
    TeamUpdate,
)
from app.services import permission_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_admin(user: dict[str, Any]) -> bool:
    return permission_service.is_admin_user(user)


def _is_manager(user: dict[str, Any]) -> bool:
    role = str(user.get("role") or "").strip().lower()
    return role in {"sales_manager", "manager"}


def _assert_team_access(current_user: dict[str, Any], team: dict[str, Any]) -> None:
    """Raise 403 if non-admin user is not the team's manager."""
    if _is_admin(current_user):
        return
    if str(current_user.get("id")) != str(team.get("manager_id")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own team",
        )


async def _get_team_by_id(db: PostgresClient, team_id: str) -> dict[str, Any]:
    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT t.*, a.full_name AS manager_name, a.email AS manager_email "
                    "FROM teams t "
                    "JOIN agents a ON a.id = t.manager_id "
                    "WHERE t.id = :team_id"
                ),
                {"team_id": team_id},
            ).mappings().first()
        return dict(row) if row else None

    team = await run_db_operation(_query)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


async def _get_team_members_with_stats(
    db: PostgresClient, team_id: str
) -> list[dict[str, Any]]:
    """Return team members enriched with lead/deal/task counts."""

    def _query():
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        a.id,
                        a.full_name,
                        a.email,
                        a.status,
                        a.role,
                        tm.joined_at,
                        (SELECT COUNT(*) FROM leads l WHERE l.owner_id = a.id)  AS leads_count,
                        (SELECT COUNT(*) FROM deals  d WHERE d.owner_id = a.id)  AS deals_count,
                        (SELECT COUNT(*) FROM tasks  t
                         WHERE t.assigned_to = a.id AND t.status NOT IN ('done','closed','completed'))
                                                                                 AS tasks_open
                    FROM team_members tm
                    JOIN agents a ON a.id = tm.agent_id
                    WHERE tm.team_id = :team_id
                    ORDER BY tm.joined_at ASC
                    """
                ),
                {"team_id": team_id},
            ).mappings().all()
        return [dict(r) for r in rows]

    return await run_db_operation(_query)


def _build_team_response(team: dict[str, Any], member_count: int = 0) -> dict[str, Any]:
    return {
        "id": team["id"],
        "name": team["name"],
        "manager_id": team["manager_id"],
        "manager_name": team.get("manager_name"),
        "manager_email": team.get("manager_email"),
        "member_count": member_count,
        "created_at": team["created_at"],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreate,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
):
    """
    Create a team.

    - Admins can create teams for themselves (they must supply manager_id via a
      separate admin-only endpoint — here we default to the current user).
    - Managers always create a team for themselves.
    - A manager can only have one team.
    """
    manager_id = str(current_user["id"])

    # Check if team already exists for this manager
    def _check():
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT id FROM teams WHERE manager_id = :mid"),
                {"mid": manager_id},
            ).first()
        return row

    existing = await run_db_operation(_check)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A team already exists for this manager",
        )

    def _insert():
        with db.engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO teams (name, manager_id) VALUES (:name, :mid) "
                    "RETURNING id, name, manager_id, created_at"
                ),
                {"name": payload.name, "mid": manager_id},
            ).mappings().first()
        return dict(row)

    team = await run_db_operation(_insert)
    return _build_team_response(team)


@router.get("", response_model=TeamList)
async def list_teams(
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
):
    """List all teams (admin only sees all; managers see only their own)."""
    is_admin_actor = _is_admin(current_user)

    def _query():
        with db.engine.connect() as conn:
            if is_admin_actor:
                rows = conn.execute(
                    text(
                        """
                        SELECT t.*, a.full_name AS manager_name, a.email AS manager_email,
                               (SELECT COUNT(*) FROM team_members tm WHERE tm.team_id = t.id) AS member_count
                        FROM teams t
                        JOIN agents a ON a.id = t.manager_id
                        ORDER BY t.created_at DESC
                        """
                    )
                ).mappings().all()
            else:
                rows = conn.execute(
                    text(
                        """
                        SELECT t.*, a.full_name AS manager_name, a.email AS manager_email,
                               (SELECT COUNT(*) FROM team_members tm WHERE tm.team_id = t.id) AS member_count
                        FROM teams t
                        JOIN agents a ON a.id = t.manager_id
                        WHERE t.manager_id = :mid
                        ORDER BY t.created_at DESC
                        """
                    ),
                    {"mid": str(current_user["id"])},
                ).mappings().all()
        return [dict(r) for r in rows]

    teams = await run_db_operation(_query)
    items = [_build_team_response(t, member_count=int(t.get("member_count", 0))) for t in teams]
    return {"items": items, "total": len(items)}


@router.get("/mine", response_model=TeamDetail)
async def get_my_team(
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
):
    """Get the current manager's own team with full member stats."""

    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT t.*, a.full_name AS manager_name, a.email AS manager_email "
                    "FROM teams t "
                    "JOIN agents a ON a.id = t.manager_id "
                    "WHERE t.manager_id = :mid"
                ),
                {"mid": str(current_user["id"])},
            ).mappings().first()
        return dict(row) if row else None

    team = await run_db_operation(_query)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You don't have a team yet. Create one first.",
        )

    members = await _get_team_members_with_stats(db, str(team["id"]))
    return {
        **_build_team_response(team),
        "members": members,
    }


@router.get("/{team_id}", response_model=TeamDetail)
async def get_team(
    team_id: UUID,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
):
    """Get team details including members with stats."""
    team = await _get_team_by_id(db, str(team_id))
    _assert_team_access(current_user, team)
    members = await _get_team_members_with_stats(db, str(team_id))
    return {
        **_build_team_response(team),
        "members": members,
    }


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: UUID,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
):
    team = await _get_team_by_id(db, str(team_id))
    _assert_team_access(current_user, team)

    def _delete():
        with db.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM team_members WHERE team_id = :tid"),
                {"tid": str(team_id)},
            )
            conn.execute(
                text("UPDATE agents SET team_id = NULL WHERE team_id = :tid"),
                {"tid": str(team_id)},
            )
            conn.execute(
                text("DELETE FROM teams WHERE id = :tid"),
                {"tid": str(team_id)},
            )

    await run_db_operation(_delete)
    return None


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: UUID,
    payload: TeamUpdate,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
):
    """Rename a team."""
    team = await _get_team_by_id(db, str(team_id))
    _assert_team_access(current_user, team)

    if not payload.name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    def _update():
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE teams SET name = :name WHERE id = :tid"),
                {"name": payload.name, "tid": str(team_id)},
            )

    await run_db_operation(_update)
    team["name"] = payload.name

    def _count():
        with db.engine.connect() as conn:
            val = conn.execute(
                text("SELECT COUNT(*) FROM team_members WHERE team_id = :tid"),
                {"tid": str(team_id)},
            ).scalar()
        return int(val or 0)

    count = await run_db_operation(_count)
    return _build_team_response(team, member_count=count)


@router.post("/{team_id}/members", status_code=status.HTTP_201_CREATED)
async def add_team_member(
    team_id: UUID,
    payload: TeamMemberAdd,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
):
    """Add a sales rep to a team."""
    team = await _get_team_by_id(db, str(team_id))
    _assert_team_access(current_user, team)

    # Validate target agent exists and is a sales_rep
    def _get_agent():
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, role, full_name FROM agents WHERE id = :aid"),
                {"aid": str(payload.agent_id)},
            ).mappings().first()
        return dict(row) if row else None

    agent = await run_db_operation(_get_agent)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    agent_role = str(agent.get("role") or "").strip().lower()
    if agent_role not in {"sales_rep", "agent"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only sales reps can be added to a team",
        )

    def _insert_member():
        with db.engine.begin() as conn:
            # Upsert to avoid duplicate key errors
            conn.execute(
                text(
                    "INSERT INTO team_members (team_id, agent_id) "
                    "VALUES (:tid, :aid) ON CONFLICT DO NOTHING"
                ),
                {"tid": str(team_id), "aid": str(payload.agent_id)},
            )
            # Also update agents.team_id for fast lookup
            conn.execute(
                text("UPDATE agents SET team_id = :tid WHERE id = :aid"),
                {"tid": str(team_id), "aid": str(payload.agent_id)},
            )

    await run_db_operation(_insert_member)
    return {"success": True, "agent_id": str(payload.agent_id), "team_id": str(team_id)}


@router.delete("/{team_id}/members/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(
    team_id: UUID,
    agent_id: UUID,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
):
    """Remove a sales rep from a team."""
    team = await _get_team_by_id(db, str(team_id))
    _assert_team_access(current_user, team)

    def _delete():
        with db.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM team_members WHERE team_id = :tid AND agent_id = :aid"),
                {"tid": str(team_id), "aid": str(agent_id)},
            )
            # Clear team_id on agent if they belonged to this team
            conn.execute(
                text(
                    "UPDATE agents SET team_id = NULL "
                    "WHERE id = :aid AND team_id = :tid"
                ),
                {"aid": str(agent_id), "tid": str(team_id)},
            )

    await run_db_operation(_delete)
    return None
