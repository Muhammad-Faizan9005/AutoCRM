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
from app.schemas.permissions import PermissionSet, PermissionUpdate
from app.services import permission_service
from app.services.admin_overview_service import AdminOverviewService
from app.services.permission_service import PermissionService, sanitize_permissions_map
from app.services.registration_service import normalize_role_input, register_user_account

router = APIRouter()

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
):
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
            clauses.append("role = :managed_role")
            params["managed_role"] = "sales_rep"

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
):
    normalized_role = normalize_role_input(payload.role)
    if not normalized_role:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported role")
    if not _is_admin(current_user) and normalized_role != "sales_rep":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managers can create sales reps only",
        )

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
    return _to_admin_user(created)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_admin_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    repository: UserRepository = Depends(get_user_repository),
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

    updated = await repository.update_by_id(str(user_id), update_data)
    return _to_admin_user(updated)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_user(
    user_id: UUID,
    current_user: dict = Depends(require_permissions(["admin_users"])),
    repository: UserRepository = Depends(get_user_repository),
):
    target_user = await repository.get_by_id(str(user_id))
    _assert_manager_scope_for_target(current_user, target_user)
    await repository.update_by_id(str(user_id), {"is_active": False, "status": "disabled"})
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
