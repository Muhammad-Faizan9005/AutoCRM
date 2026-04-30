from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreate, TaskResponse, TaskUpdate

router = APIRouter()


def get_task_repository(db: Client = Depends(get_db)) -> TaskRepository:
    return TaskRepository(db)


def _ensure_assignment_permissions(current_user: dict, assigned_to: UUID | None) -> None:
    if assigned_to is None:
        return

    role = current_user.get("role")
    requester_id = current_user.get("id")
    if role in {"admin", "sales_manager"}:
        return

    if requester_id and str(assigned_to) == str(requester_id):
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to assign task")


@router.get("/", response_model=List[TaskResponse])
async def get_tasks(
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
    assigned_to: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    priority: str | None = None,
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
):
    """Get tasks with optional filtering."""
    return await repository.list_tasks(
        skip=skip,
        limit=limit,
        status=status,
        assigned_to=str(assigned_to) if assigned_to else None,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        priority=priority,
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
):
    """Get a task by ID."""
    return await repository.get_by_id(task_id)


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
):
    """Create a new task."""
    task_data = payload.model_dump()
    _ensure_assignment_permissions(current_user, task_data.get("assigned_to"))

    if task_data.get("assigned_to") is not None:
        task_data["assigned_to"] = str(task_data["assigned_to"])

    task_data["entity_id"] = str(task_data["entity_id"])

    return await repository.create(task_data)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
):
    """Update a task."""
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "assigned_to" in update_data:
        _ensure_assignment_permissions(current_user, update_data.get("assigned_to"))
        if update_data["assigned_to"] is not None:
            update_data["assigned_to"] = str(update_data["assigned_to"])

    if "entity_id" in update_data and update_data["entity_id"] is not None:
        update_data["entity_id"] = str(update_data["entity_id"])

    return await repository.update_by_id(task_id, update_data)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user: dict = Depends(require_admin()),
    repository: TaskRepository = Depends(get_task_repository),
):
    """Delete a task."""
    await repository.delete_by_id(task_id)
    return None
