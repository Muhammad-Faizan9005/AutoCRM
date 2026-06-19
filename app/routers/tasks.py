from __future__ import annotations

from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import text
from supabase import Client

from app.auth.dependencies import require_auth
from app.database import get_db, run_db_operation
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreate, TaskResponse, TaskUpdate
from app.services.notification_service import NotificationService
from app.services.email_service import MailjetEmailService
from app.utils.statuses import TASK_STATUSES, normalize_status
from app.utils.team_access import can_access_lead, can_access_rep

router = APIRouter()

REP_TASK_STATUSES = {"in_progress", "done"}


def get_task_repository(db: Client = Depends(get_db)) -> TaskRepository:
    return TaskRepository(db)

def get_notification_service(db: Client = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


def get_email_service(db: Client = Depends(get_db)) -> MailjetEmailService:
    return MailjetEmailService(db)


def _has_task_write_role(current_user: dict) -> bool:
    role = str(current_user.get("role") or "").strip().lower()
    return role in {"admin", "manager", "sales_manager"}


async def _ensure_assignment_permissions(db: Client, current_user: dict, assigned_to: UUID | None) -> None:
    if assigned_to is None:
        return

    role = str(current_user.get("role") or "").strip().lower()
    if role == "admin":
        return

    if role in {"manager", "sales_manager"} and await can_access_rep(db, current_user, str(assigned_to)):
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to assign task")


def _can_manage_all_tasks(current_user: dict) -> bool:
    role = str(current_user.get("role") or "").strip().lower()
    return role == "admin"


async def _assert_can_write_existing_task(db: Client, current_user: dict, task: dict) -> None:
    if not _has_task_write_role(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to manage tasks")

    if _can_manage_all_tasks(current_user):
        return

    assigned_to = str(task.get("assigned_to") or "")
    if assigned_to and await can_access_rep(db, current_user, assigned_to):
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to manage this task")


def _assert_can_update_own_task_status(current_user: dict, task: dict, update_data: dict[str, Any]) -> None:
    if set(update_data.keys()) != {"status"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sales reps can only update task status")

    if update_data.get("status") not in REP_TASK_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sales reps can only set task status to in progress or done",
        )

    requester_id = str(current_user.get("id") or "")
    assigned_to = str(task.get("assigned_to") or "")
    if not requester_id or requester_id != assigned_to:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to update this task")


async def _can_access_lead(db: Client, current_user: dict, lead_id: str) -> bool:
    return await can_access_lead(db, current_user, lead_id)


async def _enrich_task_rows(db: Client, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    task_ids = [str(row.get("id")) for row in rows if row.get("id")]
    if not task_ids:
        return rows

    def _query():
        with db.engine.connect() as conn:
            enriched = conn.execute(
                text(
                    "SELECT t.id, l.name AS lead_name, a.full_name AS assignee_name, a.email AS assignee_email "
                    "FROM tasks t "
                    "LEFT JOIN leads l ON l.id = t.entity_id AND t.entity_type = 'lead' "
                    "LEFT JOIN agents a ON a.id = t.assigned_to "
                    "WHERE t.id = ANY(CAST(:task_ids AS uuid[]))"
                ),
                {"task_ids": task_ids},
            ).mappings().all()
            return {str(row["id"]): dict(row) for row in enriched}

    lookup = await run_db_operation(_query)
    output = []
    for row in rows:
        next_row = dict(row)
        info = lookup.get(str(row.get("id")), {})
        if info.get("lead_name"):
            next_row["lead_name"] = info["lead_name"]
        if info.get("assignee_name") or info.get("assignee_email"):
            next_row["assignee_name"] = info.get("assignee_name") or info.get("assignee_email")
        output.append(next_row)
    return output


async def _notify_task_assigned(
    *,
    notification_service: NotificationService,
    email_service: MailjetEmailService,
    recipient_id: str,
    actor_id: str,
    task_id: str,
    task_title: str,
    title: str = "Task assigned to you",
) -> None:
    try:
        actor_name = await notification_service.get_agent_name(actor_id)
        await notification_service.create_notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            type="task_assigned",
            title=title,
            message=f"{actor_name or 'Manager'} assigned task \"{task_title}\" to you.",
            entity_type="task",
            entity_id=task_id,
        )
        recipient_email = await email_service.get_recipient_email(recipient_id)
        if recipient_email:
            await email_service.send_task_assigned_email(
                recipient_id=recipient_id,
                recipient_email=recipient_email,
                actor_name=actor_name or "Manager",
                task_title=task_title,
            )
    except Exception:
        return


async def _notify_task_unassigned(
    *,
    notification_service: NotificationService,
    recipient_id: str,
    actor_id: str,
    task_id: str,
    task_title: str,
) -> None:
    try:
        actor_name = await notification_service.get_agent_name(actor_id)
        await notification_service.create_notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            type="task_unassigned",
            title="Task unassigned",
            message=f"{actor_name or 'Manager'} unassigned task \"{task_title}\" from you.",
            entity_type="task",
            entity_id=task_id,
        )
    except Exception:
        return


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
            can_access = await _can_access_lead(db, current_user, str(entity_id))
            if not can_access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions to view these tasks",
                )
        else:
            role = str(current_user.get("role") or "").strip().lower()
            if role in {"manager", "sales_manager"} and assigned_to is None:
                def _query_team_tasks():
                    with db.engine.connect() as conn:
                        sql = (
                            "SELECT t.* FROM tasks t "
                            "JOIN team_members tm ON tm.agent_id = t.assigned_to "
                            "JOIN teams t2 ON t2.id = tm.team_id "
                            "WHERE t2.manager_id = :mid "
                        )
                        params: dict[str, Any] = {"mid": requester_id}
                        if status:
                            sql += "AND t.status = :status "
                            params["status"] = status
                        if entity_type:
                            sql += "AND t.entity_type = :entity_type "
                            params["entity_type"] = entity_type
                        if entity_id:
                            sql += "AND t.entity_id = :entity_id "
                            params["entity_id"] = str(entity_id)
                        if priority:
                            sql += "AND t.priority = :priority "
                            params["priority"] = priority
                        sql += "ORDER BY t.due_at ASC OFFSET :skip LIMIT :limit"
                        params["skip"] = skip
                        params["limit"] = limit
                        rows = conn.execute(text(sql), params).mappings().all()
                        return [dict(row) for row in rows]

                rows = await run_db_operation(_query_team_tasks)
                return await _enrich_task_rows(db, rows)

            if assigned_to is not None:
                if not await can_access_rep(db, current_user, str(assigned_to)):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Insufficient permissions to view these tasks",
                    )
            else:
                assigned_to = UUID(requester_id) if requester_id else None

    rows = await repository.list_tasks(
        skip=skip,
        limit=limit,
        status=status,
        assigned_to=str(assigned_to) if assigned_to else None,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        priority=priority,
    )
    return await _enrich_task_rows(db, rows)


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
            can_access = await _can_access_lead(db, current_user, str(task.get("entity_id")))
            if can_access:
                return (await _enrich_task_rows(db, [task]))[0]
        if not requester_id or not await can_access_rep(db, current_user, task_assigned_to):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to view this task",
            )
    return (await _enrich_task_rows(db, [task]))[0]


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    background_tasks: BackgroundTasks,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
    notification_service: NotificationService = Depends(get_notification_service),
    email_service: MailjetEmailService = Depends(get_email_service),
):
    """Create a new task."""
    if not _has_task_write_role(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to create tasks")

    task_data = payload.model_dump()
    try:
        task_data["status"] = normalize_status(task_data.get("status") or "backlog", TASK_STATUSES)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await _ensure_assignment_permissions(db, current_user, task_data.get("assigned_to"))

    if task_data.get("assigned_to") is not None:
        task_data["assigned_to"] = str(task_data["assigned_to"])

    task_data["entity_id"] = str(task_data["entity_id"])

    created = await repository.create(task_data)
    assigned_to = str(created.get("assigned_to") or "")
    actor_id = str(current_user.get("id") or "")
    if assigned_to and assigned_to != actor_id:
        background_tasks.add_task(
            _notify_task_assigned,
            notification_service=notification_service,
            email_service=email_service,
            recipient_id=assigned_to,
            actor_id=actor_id,
            task_id=str(created.get("id")),
            task_title=created.get("title") or "Untitled Task",
            title="New task assigned",
        )
    return (await _enrich_task_rows(db, [created]))[0]


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    background_tasks: BackgroundTasks,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: TaskRepository = Depends(get_task_repository),
    notification_service: NotificationService = Depends(get_notification_service),
    email_service: MailjetEmailService = Depends(get_email_service),
):
    """Update a task."""
    existing_task = await repository.get_by_id(task_id)
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "status" in update_data and update_data["status"] is not None:
        try:
            update_data["status"] = normalize_status(update_data["status"], TASK_STATUSES)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if _has_task_write_role(current_user):
        await _assert_can_write_existing_task(db, current_user, existing_task)
    else:
        _assert_can_update_own_task_status(current_user, existing_task, update_data)

    if "assigned_to" in update_data:
        await _ensure_assignment_permissions(db, current_user, update_data.get("assigned_to"))
        if update_data["assigned_to"] is not None:
            update_data["assigned_to"] = str(update_data["assigned_to"])

    if "entity_id" in update_data and update_data["entity_id"] is not None:
        update_data["entity_id"] = str(update_data["entity_id"])

    updated = await repository.update_by_id(task_id, update_data)
    old_assignee = str(existing_task.get("assigned_to") or "")
    new_assignee = str(updated.get("assigned_to") or "")
    actor_id = str(current_user.get("id") or "")
    task_title = updated.get("title") or "Untitled Task"
    task_id_text = str(updated.get("id"))
    if old_assignee and old_assignee != new_assignee and old_assignee != actor_id:
        background_tasks.add_task(
            _notify_task_unassigned,
            notification_service=notification_service,
            recipient_id=old_assignee,
            actor_id=actor_id,
            task_id=task_id_text,
            task_title=task_title,
        )
    if new_assignee and new_assignee != old_assignee and new_assignee != actor_id:
        background_tasks.add_task(
            _notify_task_assigned,
            notification_service=notification_service,
            email_service=email_service,
            recipient_id=new_assignee,
            actor_id=actor_id,
            task_id=task_id_text,
            task_title=task_title,
        )
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
    await _assert_can_write_existing_task(db, current_user, existing_task)

    await repository.delete_by_id(task_id)
    return None
