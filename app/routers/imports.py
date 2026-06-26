from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from supabase import Client

from app.auth.dependencies import require_permissions
from app.database import get_db
from app.schemas.imports import ImportResult
from app.services.import_service import ImportService


router = APIRouter()


def get_import_service(db: Client = Depends(get_db)) -> ImportService:
    return ImportService(db)


def _default_import_owner_id(current_user: dict) -> str | None:
    role = str(current_user.get("role") or "").strip().lower()
    if role == "admin":
        return None
    return str(current_user.get("id") or "") or None


async def _validate_uploaded_file(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file must have a filename")


@router.post("/leads", response_model=ImportResult)
async def import_leads(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_permissions(["import_data"])),
    service: ImportService = Depends(get_import_service),
):
    """Import lead rows from CSV or Excel file."""
    await _validate_uploaded_file(file)
    file_bytes = await file.read()
    return await service.import_leads(
        file_name=file.filename,
        file_bytes=file_bytes,
        owner_id=_default_import_owner_id(current_user),
    )


@router.post("/customers", response_model=ImportResult)
async def import_customers(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_permissions(["import_data"])),
    service: ImportService = Depends(get_import_service),
):
    """Compatibility alias for lead import."""
    await _validate_uploaded_file(file)
    file_bytes = await file.read()
    return await service.import_leads(
        file_name=file.filename,
        file_bytes=file_bytes,
        owner_id=_default_import_owner_id(current_user),
    )


@router.post("/tickets", response_model=ImportResult)
async def import_tickets(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_permissions(["import_data"])),
    service: ImportService = Depends(get_import_service),
):
    """Import ticket rows from CSV or Excel file."""
    await _validate_uploaded_file(file)
    file_bytes = await file.read()
    return await service.import_tickets(file_name=file.filename, file_bytes=file_bytes)
