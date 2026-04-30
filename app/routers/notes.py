from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db
from app.repositories.note_repository import NoteRepository
from app.schemas.note import NoteCreate, NoteResponse, NoteUpdate

router = APIRouter()


def get_note_repository(db: Client = Depends(get_db)) -> NoteRepository:
    return NoteRepository(db)


@router.get("/", response_model=List[NoteResponse])
async def get_notes(
    skip: int = 0,
    limit: int = 100,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    author_id: UUID | None = None,
    current_user: dict = Depends(require_auth),
    repository: NoteRepository = Depends(get_note_repository),
):
    """Get notes with optional filtering."""
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
    current_user: dict = Depends(require_auth),
    repository: NoteRepository = Depends(get_note_repository),
):
    """Get a note by ID."""
    return await repository.get_by_id(note_id)


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreate,
    current_user: dict = Depends(require_auth),
    repository: NoteRepository = Depends(get_note_repository),
):
    """Create a note."""
    note_data = payload.model_dump()
    note_data["author_id"] = str(current_user.get("id")) if current_user.get("id") else None
    note_data["entity_id"] = str(note_data["entity_id"])

    return await repository.create(note_data)


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    payload: NoteUpdate,
    current_user: dict = Depends(require_auth),
    repository: NoteRepository = Depends(get_note_repository),
):
    """Update a note."""
    existing_note = await repository.get_by_id(note_id)
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
    current_user: dict = Depends(require_auth),
    repository: NoteRepository = Depends(get_note_repository),
):
    """Delete a note."""
    existing_note = await repository.get_by_id(note_id)
    requester_id = str(current_user.get("id"))
    requester_role = current_user.get("role")
    author_id = str(existing_note.get("author_id")) if existing_note.get("author_id") else None

    if requester_role != "admin" and author_id and requester_id != author_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    await repository.delete_by_id(note_id)
    return None
