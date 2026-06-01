from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth.dependencies import require_auth
from app.database import get_db
from app.repositories.note_repository import NoteRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.agent_action import AgentActionIn
from app.schemas.note import NoteCreate
from app.schemas.task import TaskCreate
from app.services.notification_service import NotificationService

router = APIRouter()


def get_task_repository(db: Client = Depends(get_db)) -> TaskRepository:
    return TaskRepository(db)


def get_note_repository(db: Client = Depends(get_db)) -> NoteRepository:
    return NoteRepository(db)


def get_notification_service(db: Client = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


@router.post("/actions", status_code=status.HTTP_202_ACCEPTED)
async def dispatch_agent_action(
    payload: AgentActionIn,
    current_user: dict = Depends(require_auth),
    task_repository: TaskRepository = Depends(get_task_repository),
    note_repository: NoteRepository = Depends(get_note_repository),
    notification_service: NotificationService = Depends(get_notification_service),
):
    action_type = payload.action_type.strip().lower()
    if action_type == "create_task":
        data = payload.data
        task_payload = TaskCreate(
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            title=str(data.get("title") or "Agent task"),
            description=data.get("description"),
            assigned_to=data.get("assigned_to"),
            status=data.get("status") or "backlog",
            priority=data.get("priority") or "medium",
            due_at=_parse_datetime(data.get("due_at")),
        )
        created = await task_repository.create(task_payload.model_dump())
        return {"status": "created", "action_type": payload.action_type, "id": created.get("id")}

    if action_type == "create_note":
        data = payload.data
        note_payload = NoteCreate(
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            content=str(data.get("content") or payload.reason),
            author_id=UUID(str(current_user.get("id"))) if current_user.get("id") else None,
        )
        created = await note_repository.create(note_payload.model_dump())
        return {"status": "created", "action_type": payload.action_type, "id": created.get("id")}

    if action_type == "create_alert":
        data = payload.data
        recipient_id = data.get("recipient_id")
        if not recipient_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="recipient_id is required")
        created = await notification_service.create_notification(
            recipient_id=str(recipient_id),
            actor_id=str(current_user.get("id") or ""),
            type="agent_alert",
            title=str(data.get("title") or "Agent alert"),
            message=str(data.get("message") or payload.reason),
            entity_type=payload.entity_type,
            entity_id=str(payload.entity_id),
        )
        return {"status": "created", "action_type": payload.action_type, "id": created.get("id") if created else None}

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action_type")


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
