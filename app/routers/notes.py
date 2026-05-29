from __future__ import annotations

from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db, run_db_operation
from app.repositories.note_repository import NoteRepository
from app.schemas.note import NoteCreate, NoteResponse, NoteUpdate
from app.services.notification_service import NotificationService
from app.utils.team_access import can_access_lead

router = APIRouter()


def get_note_repository(db: Client = Depends(get_db)) -> NoteRepository:
    return NoteRepository(db)

def get_notification_service(db: Client = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


def _is_lead_note(entity_type: str | None) -> bool:
    return (entity_type or "").strip().lower() == "lead"


def _can_manage_lead_notes(current_user: dict[str, Any]) -> bool:
    role = str(current_user.get("role") or "").strip().lower()
    return role == "admin"


async def _can_access_lead(db: Client, current_user: dict[str, Any], lead_id: str) -> bool:
    return await can_access_lead(db, current_user, lead_id)


async def _get_lead_owner_and_name(db: Client, lead_id: str) -> tuple[str | None, str | None]:
    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT owner_id, name FROM leads WHERE id = :lead_id"),
                {"lead_id": lead_id},
            ).mappings().first()
            if not row:
                return None, None
            owner = str(row.get("owner_id")) if row.get("owner_id") else None
            name = str(row.get("name")) if row.get("name") else None
            return owner, name

    return await run_db_operation(_query)


@router.get("/", response_model=List[NoteResponse])
async def get_notes(
    skip: int = 0,
    limit: int = 100,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    author_id: UUID | None = None,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: NoteRepository = Depends(get_note_repository),
):
    """Get notes with optional filtering."""
    if _is_lead_note(entity_type):
        if _can_manage_lead_notes(current_user):
            return await repository.list_notes(
                skip=skip,
                limit=limit,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id else None,
                author_id=str(author_id) if author_id else None,
            )

        def _query_lead_notes():
            with db.engine.connect() as conn:
                role = str(current_user.get("role") or "").strip().lower()
                sql = (
                    "SELECT n.* FROM notes n "
                    "JOIN leads l ON l.id = n.entity_id "
                )
                params: dict[str, Any] = {}

                if role in {"manager", "sales_manager"}:
                    sql += (
                        "JOIN team_members tm ON tm.agent_id = l.owner_id "
                        "JOIN teams t ON t.id = tm.team_id "
                        "WHERE t.manager_id = :mid "
                    )
                    params["mid"] = str(current_user.get("id") or "")
                else:
                    sql += "WHERE l.owner_id = :uid "
                    params["uid"] = str(current_user.get("id") or "")

                sql += "AND n.entity_type = 'lead' "
                if entity_id:
                    sql += "AND n.entity_id = :entity_id "
                    params["entity_id"] = str(entity_id)
                if author_id:
                    sql += "AND n.author_id = :author_id "
                    params["author_id"] = str(author_id)
                sql += "ORDER BY n.created_at DESC OFFSET :skip LIMIT :limit"
                params["skip"] = skip
                params["limit"] = limit
                return conn.execute(text(sql), params).mappings().all()

        rows = await run_db_operation(_query_lead_notes)
        return [dict(row) for row in rows]

    return await repository.list_notes(
        skip=skip,
        limit=limit,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        author_id=str(author_id) if author_id else None,
    )


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: NoteRepository = Depends(get_note_repository),
):
    """Get a note by ID."""
    note = await repository.get_by_id(note_id)
    if _is_lead_note(note.get("entity_type")):
        if _can_manage_lead_notes(current_user):
            return note
        can_access = await _can_access_lead(db, current_user, str(note.get("entity_id")))
        if not can_access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return note


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreate,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: NoteRepository = Depends(get_note_repository),
    notification_service: NotificationService = Depends(get_notification_service),
):
    """Create a note."""
    note_data = payload.model_dump()
    if _is_lead_note(note_data.get("entity_type")):
        if not _can_manage_lead_notes(current_user):
            can_create = await _can_access_lead(db, current_user, str(note_data["entity_id"]))
            if not can_create:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only create notes for your assigned leads",
                )

    note_data["author_id"] = str(current_user.get("id")) if current_user.get("id") else None
    note_data["entity_id"] = str(note_data["entity_id"])

    created = await repository.create(note_data)

    if _is_lead_note(created.get("entity_type")):
        lead_owner_id, lead_name = await _get_lead_owner_and_name(db, str(created.get("entity_id")))
        actor_id = str(current_user.get("id") or "")
        if lead_owner_id and lead_owner_id != actor_id:
            actor_name = await notification_service.get_agent_name(actor_id)
            await notification_service.create_notification(
                recipient_id=lead_owner_id,
                actor_id=actor_id,
                type="note_added",
                title="New note added",
                message=f"{actor_name or 'Manager'} added a note on lead \"{lead_name or 'Lead'}\".",
                entity_type="note",
                entity_id=str(created.get("id")),
            )

    return created


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    payload: NoteUpdate,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: NoteRepository = Depends(get_note_repository),
):
    """Update a note."""
    existing_note = await repository.get_by_id(note_id)
    if _is_lead_note(existing_note.get("entity_type")):
        if not _can_manage_lead_notes(current_user):
            can_access = await _can_access_lead(db, current_user, str(existing_note.get("entity_id")))
            if not can_access:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    requester_id = str(current_user.get("id"))
    requester_role = current_user.get("role")
    author_id = str(existing_note.get("author_id")) if existing_note.get("author_id") else None

    if requester_role != "admin" and author_id and requester_id != author_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    return await repository.update_by_id(note_id, update_data)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: NoteRepository = Depends(get_note_repository),
):
    """Delete a note."""
    existing_note = await repository.get_by_id(note_id)
    if _is_lead_note(existing_note.get("entity_type")):
        if not _can_manage_lead_notes(current_user):
            can_access = await _can_access_lead(db, current_user, str(existing_note.get("entity_id")))
            if not can_access:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    requester_id = str(current_user.get("id"))
    requester_role = current_user.get("role")
    author_id = str(existing_note.get("author_id")) if existing_note.get("author_id") else None

    if requester_role != "admin" and author_id and requester_id != author_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    await repository.delete_by_id(note_id)
    return None
