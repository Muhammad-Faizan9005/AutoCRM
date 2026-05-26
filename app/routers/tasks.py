from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db, run_db_operation
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreate, TaskResponse, TaskUpdate
from app.services.notification_service import NotificationService
from app.services.email_service import MailjetEmailService
from app.utils.statuses import TASK_STATUSES, normalize_status

router = APIRouter()


def get_task_repository(db: Client = Depends(get_db)) -> TaskRepository:
    return TaskRepository(db)

def get_notification_service(db: Client = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


def get_email_service(db: Client = Depends(get_db)) -> MailjetEmailService:
    return MailjetEmailService(db)


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


def _can_manage_all_tasks(current_user: dict) -> bool:
    role = str(current_user.get("role") or "").strip().lower()
    return role in {"admin", "sales_manager", "manager"}


async def _is_lead_owner(db: Client, current_user: dict, lead_id: str) -> bool:
    user_id = str(current_user.get("id") or "")
    if not user_id:
        return False

    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT owner_id FROM leads WHERE id = :lead_id"),
                {"lead_id": lead_id},
            ).mappings().first()
            return str(row.get("owner_id")) if row and row.get("owner_id") else None

    owner_id = await run_db_operation(_query)
    return bool(owner_id and owner_id == user_id)


@router.get("/", response_model=List[TaskResponse])
async def get_tasks(
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
    assigned_to: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    priority: str | None = None,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
):
    """Get tasks with optional filtering."""
    requester_id = str(current_user.get("id") or "")
    if not _can_manage_all_tasks(current_user):
        if (entity_type or "").strip().lower() == "lead" and entity_id:
            is_owner = await _is_lead_owner(db, current_user, str(entity_id))
            if not is_owner:
                if assigned_to is not None and str(assigned_to) != requester_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Insufficient permissions to view these tasks",
                    )
                assigned_to = UUID(requester_id) if requester_id else None
        else:
            if assigned_to is not None and str(assigned_to) != requester_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions to view these tasks",
                )
            assigned_to = UUID(requester_id) if requester_id else None

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
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
):
    """Get a task by ID."""
    task = await repository.get_by_id(task_id)
    if not _can_manage_all_tasks(current_user):
        requester_id = str(current_user.get("id") or "")
        task_assigned_to = str(task.get("assigned_to") or "")
        if (task.get("entity_type") or "").strip().lower() == "lead":
            is_owner = await _is_lead_owner(db, current_user, str(task.get("entity_id")))
            if is_owner:
                return task
        if not requester_id or task_assigned_to != requester_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to view this task",
            )
    return task


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
    notification_service: NotificationService = Depends(get_notification_service),
    email_service: MailjetEmailService = Depends(get_email_service),
):
    """Create a new task."""
    task_data = payload.model_dump()
    try:
        task_data["status"] = normalize_status(task_data.get("status") or "open", TASK_STATUSES)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    _ensure_assignment_permissions(current_user, task_data.get("assigned_to"))

    if task_data.get("assigned_to") is not None:
        task_data["assigned_to"] = str(task_data["assigned_to"])

    task_data["entity_id"] = str(task_data["entity_id"])

    created = await repository.create(task_data)
    assigned_to = str(created.get("assigned_to") or "")
    actor_id = str(current_user.get("id") or "")
    if assigned_to and assigned_to != actor_id:
        actor_name = await notification_service.get_agent_name(actor_id)
        await notification_service.create_notification(
            recipient_id=assigned_to,
            actor_id=actor_id,
            type="task_assigned",
            title="New task assigned",
            message=f"{actor_name or 'Manager'} assigned task \"{created.get('title') or 'Untitled Task'}\" to you.",
            entity_type="task",
            entity_id=str(created.get("id")),
        )
        try:
            recipient_email = await email_service.get_recipient_email(assigned_to)
            if recipient_email:
                await email_service.send_task_assigned_email(
                    recipient_id=assigned_to,
                    recipient_email=recipient_email,
                    actor_name=actor_name or "Manager",
                    task_title=created.get("title") or "Untitled Task",
                )
        except Exception:
            pass
    return created


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
    notification_service: NotificationService = Depends(get_notification_service),
    email_service: MailjetEmailService = Depends(get_email_service),
):
    """Update a task."""
    existing_task = await repository.get_by_id(task_id)
    if not _can_manage_all_tasks(current_user):
        requester_id = str(current_user.get("id") or "")
        task_assigned_to = str(existing_task.get("assigned_to") or "")
        if not requester_id or task_assigned_to != requester_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to update this task",
            )

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "status" in update_data and update_data["status"] is not None:
        try:
            update_data["status"] = normalize_status(update_data["status"], TASK_STATUSES)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if "assigned_to" in update_data:
        _ensure_assignment_permissions(current_user, update_data.get("assigned_to"))
        if update_data["assigned_to"] is not None:
            update_data["assigned_to"] = str(update_data["assigned_to"])

    if "entity_id" in update_data and update_data["entity_id"] is not None:
        update_data["entity_id"] = str(update_data["entity_id"])

    updated = await repository.update_by_id(task_id, update_data)
    old_assignee = str(existing_task.get("assigned_to") or "")
    new_assignee = str(updated.get("assigned_to") or "")
    actor_id = str(current_user.get("id") or "")
    if old_assignee and old_assignee != new_assignee and old_assignee != actor_id:
        actor_name = await notification_service.get_agent_name(actor_id)
        await notification_service.create_notification(
            recipient_id=old_assignee,
            actor_id=actor_id,
            type="task_unassigned",
            title="Task unassigned",
            message=f"{actor_name or 'Manager'} unassigned task \"{updated.get('title') or 'Untitled Task'}\" from you.",
            entity_type="task",
            entity_id=str(updated.get("id")),
        )
    if new_assignee and new_assignee != old_assignee and new_assignee != actor_id:
        actor_name = await notification_service.get_agent_name(actor_id)
        await notification_service.create_notification(
            recipient_id=new_assignee,
            actor_id=actor_id,
            type="task_assigned",
            title="Task assigned to you",
            message=f"{actor_name or 'Manager'} assigned task \"{updated.get('title') or 'Untitled Task'}\" to you.",
            entity_type="task",
            entity_id=str(updated.get("id")),
        )
        try:
            recipient_email = await email_service.get_recipient_email(new_assignee)
            if recipient_email:
                await email_service.send_task_assigned_email(
                    recipient_id=new_assignee,
                    recipient_email=recipient_email,
                    actor_name=actor_name or "Manager",
                    task_title=updated.get("title") or "Untitled Task",
                )
        except Exception:
            pass
    return updated


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
):
    """Delete a task."""
    existing_task = await repository.get_by_id(task_id)
    if not _can_manage_all_tasks(current_user):
        requester_id = str(current_user.get("id") or "")
        task_assigned_to = str(existing_task.get("assigned_to") or "")
        if (existing_task.get("entity_type") or "").strip().lower() == "lead":
            is_owner = await _is_lead_owner(db, current_user, str(existing_task.get("entity_id")))
            if is_owner:
                await repository.delete_by_id(task_id)
                return None
        if not requester_id or task_assigned_to != requester_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to delete this task",
            )

    await repository.delete_by_id(task_id)
    return None
