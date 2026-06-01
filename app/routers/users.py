from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db
from app.exceptions.custom_exceptions import ValidationError
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.services.registration_service import register_user_account

router = APIRouter()


def get_user_repository(db: Client = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def _sanitize_user_payload(user: dict) -> dict:
    safe_user = dict(user)
    safe_user.pop("password_hash", None)
    return safe_user


@router.get("/", response_model=list[UserResponse])
async def list_users(
    current_user: dict = Depends(require_auth),
    repository: UserRepository = Depends(get_user_repository),
):
    """List all users. Admin only, except for the AI service account."""
    requester_role = str(current_user.get("role") or "").strip().lower()
    requester_email = str(current_user.get("email") or "").strip().lower()

    if requester_role != "admin" and requester_email != "agent.action@autocrm.internal":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    users = await repository.list(limit=1000)
    return [_sanitize_user_payload(row) for row in users]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: dict = Depends(require_auth),
    repository: UserRepository = Depends(get_user_repository),
):
    """Get user details. Admin can view all; others can view themselves."""
    requester_id = str(current_user.get("id"))
    requester_role = current_user.get("role")
    target_id = str(user_id)

    if requester_role != "admin" and requester_id != target_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    user = await repository.get_by_id(target_id)
    return _sanitize_user_payload(user)


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    current_user: dict = Depends(require_admin()),
    repository: UserRepository = Depends(get_user_repository),
):
    """Create a new user. Admin only."""
    created = await register_user_account(
        repository.db,
        email=str(payload.email),
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,
    )
    return _sanitize_user_payload(created)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    current_user: dict = Depends(require_auth),
    repository: UserRepository = Depends(get_user_repository),
):
    """Update user profile; role/status changes are admin-only."""
    requester_id = str(current_user.get("id"))
    requester_role = current_user.get("role")
    target_id = str(user_id)

    if requester_role != "admin" and requester_id != target_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise ValidationError(detail="No fields to update")

    if requester_role != "admin" and ({"role", "is_active"} & set(update_data.keys())):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can update role or activation status",
        )

    if "password" in update_data:
        update_data["password_hash"] = hash_password(update_data.pop("password"))

    updated = await repository.update_by_id(target_id, update_data)
    return _sanitize_user_payload(updated)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    current_user: dict = Depends(require_admin()),
    repository: UserRepository = Depends(get_user_repository),
):
    """Deactivate user account. Admin only."""
    await repository.update_by_id(str(user_id), {"is_active": False})

    return None
