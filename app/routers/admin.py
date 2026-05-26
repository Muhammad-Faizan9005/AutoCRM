from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text

from app.auth.dependencies import require_permissions
from app.auth.utils import hash_password
from app.database import get_db, run_db_operation
from app.postgres_client import PostgresClient
from app.repositories.user_repository import UserRepository
from app.schemas.admin import (
    AdminOverview,
    AdminUserCreate,
    AdminUserList,
    AdminUserResponse,
    AdminUserUpdate,
)
from app.schemas.failed_invite import FailedInviteResponse
from app.schemas.permissions import PermissionSet, PermissionUpdate
from app.services import permission_service
from app.services.admin_overview_service import AdminOverviewService
from app.services.email_service import MailjetEmailService
from app.services.invite_service import InviteService
from app.services.permission_service import PermissionService, sanitize_permissions_map
from app.services.registration_service import normalize_role_input, register_user_account
from app.utils.cache import invalidate_user_cache

router = APIRouter()


async def _auto_assign_to_team(db: PostgresClient, team_id: str, agent_id: str) -> None:
    """Add the agent to the given team (team_members + agents.team_id)."""
    def _exec():
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO team_members (team_id, agent_id) "
                    "VALUES (:tid, :aid) ON CONFLICT DO NOTHING"
                ),
                {"tid": team_id, "aid": agent_id},
            )
            conn.execute(
                text("UPDATE agents SET team_id = :tid WHERE id = :aid"),
                {"tid": team_id, "aid": agent_id},
            )
    await run_db_operation(_exec)


ROLE_OUTPUT_MAP = {
    "admin": "admin",
    "sales_manager": "manager",
    "sales_rep": "agent",
}


def get_user_repository(db: PostgresClient = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_permission_service(db: PostgresClient = Depends(get_db)) -> PermissionService:
    return PermissionService(db)


def get_overview_service(db: PostgresClient = Depends(get_db)) -> AdminOverviewService:
    return AdminOverviewService(db)


def get_email_service(db: PostgresClient = Depends(get_db)) -> MailjetEmailService:
    return MailjetEmailService(db)


def get_invite_service(
    db: PostgresClient = Depends(get_db),
    email_service: MailjetEmailService = Depends(get_email_service),
) -> InviteService:
    return InviteService(db, email_service=email_service)


def _map_role_output(role: str | None) -> str:
    if not role:
        return "agent"
    return ROLE_OUTPUT_MAP.get(role, role)


def _resolve_status(user: dict[str, Any]) -> str:
    status = user.get("status")
    if status:
        return str(status)
    return "active" if user.get("is_active", True) else "disabled"


def _status_to_active(status: str) -> bool:
    return status == "active"


def _normalize_role_value(role: str | None) -> str:
    if not role:
        return ""
    return str(role).strip().lower().replace("-", "_").replace(" ", "_")


def _is_sales_rep_role(role: str | None) -> bool:
    return _normalize_role_value(role) in {"sales_rep", "agent"}


def _assert_manager_scope_for_target(current_user: dict[str, Any], target_user: dict[str, Any]) -> None:
    if _is_admin(current_user):
        return
    if not _is_sales_rep_role(target_user.get("role")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managers can manage sales reps only",
        )


def _is_admin(user: dict[str, Any]) -> bool:
    return permission_service.is_admin_user(user)


def _to_admin_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id"),
        "full_name": user.get("full_name"),
        "email": user.get("email"),
        "role": _map_role_output(user.get("role")),
        "status": _resolve_status(user),
    }


@router.get("/overview", response_model=AdminOverview)
async def get_admin_overview(
    current_user: dict = Depends(require_permissions(["admin_panel"])),
    service: AdminOverviewService = Depends(get_overview_service),
):
    return await service.get_overview()


@router.get("/users", response_model=AdminUserList)
async def list_admin_users(
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
    invite_service: InviteService = Depends(get_invite_service),
):
    await invite_service.cleanup_expired_invites()
    requester_is_admin = _is_admin(current_user)
    safe_page = max(page, 1)
    safe_page_size = max(1, min(page_size, 200))
    offset = (safe_page - 1) * safe_page_size

    def _query() -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if search:
            clauses.append("(email ILIKE :term OR full_name ILIKE :term OR role ILIKE :term)")
            params["term"] = f"%{search}%"

        if not requester_is_admin:
            # Managers only see reps in their own team
            params["manager_id"] = str(current_user["id"])
            clauses.append(
                "id IN ("
                "  SELECT tm.agent_id FROM team_members tm "
                "  JOIN teams t ON t.id = tm.team_id "
                "  WHERE t.manager_id = :manager_id"
                ")"
            )

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        list_params = {**params, "offset": offset, "limit": safe_page_size}

        query = text(
            "SELECT * FROM agents "
            + where
            + " ORDER BY created_at DESC OFFSET :offset LIMIT :limit"
        )
        count_query = text("SELECT COUNT(*) FROM agents " + where)

        with db.engine.connect() as conn:
            rows = conn.execute(query, list_params).mappings().all()
            total = conn.execute(count_query, params).scalar()

        return [dict(row) for row in rows], int(total or 0)

    users, total = await run_db_operation(_query)

    return {
        "items": [_to_admin_user(user) for user in users],
        "total": total,
    }


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
async def create_admin_user(
    payload: AdminUserCreate,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    repository: UserRepository = Depends(get_user_repository),
    invite_service: InviteService = Depends(get_invite_service),
):
    normalized_role = normalize_role_input(payload.role)
    if not normalized_role:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported role")
    if not _is_admin(current_user) and normalized_role != "sales_rep":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managers can create sales reps only",
        )

    # --- Resolve team_id for sales reps ---
    is_admin_actor = _is_admin(current_user)
    team_id_to_assign: str | None = None

    if normalized_role == "sales_rep":
        if is_admin_actor:
            # Admin must specify which team to add the rep to
            if not payload.team_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="team_id is required when creating a sales rep",
                )
            # Verify the team exists
            def _verify_team():
                with repository.db.engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT id FROM teams WHERE id = :tid"),
                        {"tid": str(payload.team_id)},
                    ).first()
                    return row
            team_row = await run_db_operation(_verify_team)
            if not team_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team not found",
                )
            team_id_to_assign = str(payload.team_id)
        else:
            # Manager — look up their own team
            def _find_manager_team():
                with repository.db.engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT id FROM teams WHERE manager_id = :mid"),
                        {"mid": str(current_user["id"])},
                    ).first()
                    return row
            team_row = await run_db_operation(_find_manager_team)
            if not team_row:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="You must create a team before adding sales reps",
                )
            team_id_to_assign = str(team_row[0])

    status_value = payload.status
    is_active = _status_to_active(status_value)

    password = payload.password
    if not password and status_value == "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is required for active users",
        )

    if not password:
        password = secrets.token_urlsafe(16)

    created = await register_user_account(
        repository.db,
        email=str(payload.email),
        password=password,
        full_name=payload.full_name,
        role=normalized_role,
        is_active=is_active,
        status_value=status_value,
    )

    # Assign the new sales rep to the resolved team
    if team_id_to_assign and normalized_role == "sales_rep":
        await _auto_assign_to_team(
            repository.db,
            team_id=team_id_to_assign,
            agent_id=str(created["id"]),
        )

    if status_value == "invited":
        await invite_service.create_invite(
            agent_id=str(created["id"]),
            email=str(created.get("email")),
            role=str(created.get("role")),
            invited_by=str(current_user.get("id") or "") or None,
        )

    return _to_admin_user(created)
@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_admin_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    repository: UserRepository = Depends(get_user_repository),
    invite_service: InviteService = Depends(get_invite_service),
):
    target_user = await repository.get_by_id(str(user_id))
    _assert_manager_scope_for_target(current_user, target_user)

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "role" in update_data:
        normalized_role = normalize_role_input(update_data.get("role"))
        if not normalized_role:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported role")
        if not _is_admin(current_user) and normalized_role != "sales_rep":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Managers can assign sales rep role only",
            )
        update_data["role"] = normalized_role

    if "status" in update_data:
        status_value = update_data["status"]
        update_data["is_active"] = _status_to_active(status_value)

    if "email" in update_data:
        existing = await repository.find_by_email(str(update_data["email"]))
        if existing and str(existing.get("id")) != str(user_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    if "password" in update_data:
        update_data["password_hash"] = hash_password(update_data.pop("password"))

    if update_data.get("status") == "disabled" and str(target_user.get("status")) == "invited":
        await invite_service.revoke_invited_user(str(user_id), reason="revoked")
        invalidate_user_cache(str(user_id))
        return _to_admin_user({**target_user, "status": "disabled", "is_active": False})

    updated = await repository.update_by_id(str(user_id), update_data)
    invalidate_user_cache(str(user_id))
    return _to_admin_user(updated)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_user(
    user_id: UUID,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    repository: UserRepository = Depends(get_user_repository),
    invite_service: InviteService = Depends(get_invite_service),
):
    target_user = await repository.get_by_id(str(user_id))
    _assert_manager_scope_for_target(current_user, target_user)
    if str(target_user.get("status")) == "invited":
        await invite_service.revoke_invited_user(str(user_id), reason="revoked")
        return None
    await repository.update_by_id(str(user_id), {"is_active": False, "status": "disabled"})
    invalidate_user_cache(str(user_id))
    return None


@router.post("/invites/{user_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    user_id: UUID,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    repository: UserRepository = Depends(get_user_repository),
    invite_service: InviteService = Depends(get_invite_service),
):
    target_user = await repository.get_by_id(str(user_id))
    _assert_manager_scope_for_target(current_user, target_user)
    if str(target_user.get("status")) != "invited":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not invited")
    await invite_service.revoke_invited_user(str(user_id), reason="revoked")
    return None


@router.get("/failed-invites", response_model=list[FailedInviteResponse])
async def list_failed_invites(
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
):
    is_admin = _is_admin(current_user)
    requester_id = str(current_user.get("id") or "")

    def _query():
        with db.engine.connect() as conn:
            if is_admin:
                rows = conn.execute(
                    text("SELECT * FROM failed_invites ORDER BY failed_at DESC")
                ).mappings().all()
            else:
                rows = conn.execute(
                    text(
                        "SELECT * FROM failed_invites "
                        "WHERE invited_by = :invited_by ORDER BY failed_at DESC"
                    ),
                    {"invited_by": requester_id},
                ).mappings().all()
            return [dict(row) for row in rows]

    return await run_db_operation(_query)


@router.post("/failed-invites/{failed_id}/reinvite", response_model=AdminUserResponse)
async def reinvite_failed_invite(
    failed_id: UUID,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    db: PostgresClient = Depends(get_db),
    invite_service: InviteService = Depends(get_invite_service),
):
    failed = await invite_service.get_failed_invite(str(failed_id))
    if not failed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Failed invite not found")

    role_value = _normalize_role_value(str(failed.get("role")))
    if not _is_admin(current_user) and role_value != "sales_rep":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managers can reinvite sales reps only")

    fallback_team_id = None
    if role_value == "sales_rep" and not failed.get("team_id"):
        def _find_manager_team():
            with db.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT id FROM teams WHERE manager_id = :mid"),
                    {"mid": str(current_user.get("id"))},
                ).first()
                return row
        team_row = await run_db_operation(_find_manager_team)
        if team_row:
            fallback_team_id = str(team_row[0])

    recreated = await invite_service.reinvite_failed_invite(
        str(failed_id),
        inviter_id=str(current_user.get("id") or "") or None,
        require_team_for_rep=_is_admin(current_user),
        fallback_team_id=fallback_team_id,
    )
    return _to_admin_user(recreated)


@router.delete("/failed-invites/{failed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_failed_invite(
    failed_id: UUID,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    invite_service: InviteService = Depends(get_invite_service),
):
    failed = await invite_service.get_failed_invite(str(failed_id))
    if not failed:
        return None
    if not _is_admin(current_user) and str(failed.get("invited_by")) != str(current_user.get("id")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    await invite_service.delete_failed_invite(str(failed_id))
    return None


@router.get("/users/{user_id}/permissions", response_model=PermissionSet)
async def get_user_permissions(
    user_id: UUID,
    current_user: dict = Depends(require_permissions(["admin_permissions"])),
    repository: UserRepository = Depends(get_user_repository),
    permission_service: PermissionService = Depends(get_permission_service),
):
    user = await repository.get_by_id(str(user_id))
    _assert_manager_scope_for_target(current_user, user)
    permissions = await permission_service.get_effective_permissions(user)
    return {"user_id": user_id, "permissions": permissions}


@router.put("/users/{user_id}/permissions", response_model=PermissionSet)
async def update_user_permissions(
    user_id: UUID,
    payload: PermissionUpdate,
    current_user: dict = Depends(require_permissions(["admin_permissions"])),
    repository: UserRepository = Depends(get_user_repository),
    permission_service: PermissionService = Depends(get_permission_service),
):
    user = await repository.get_by_id(str(user_id))
    _assert_manager_scope_for_target(current_user, user)

    sanitized = sanitize_permissions_map(payload.permissions)
    if payload.permissions and not sanitized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid permission keys provided",
        )

    await permission_service.set_permissions(user, sanitized)
    effective = await permission_service.get_effective_permissions(user)
    return {"user_id": user_id, "permissions": effective}
