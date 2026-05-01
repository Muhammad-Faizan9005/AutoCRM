from __future__ import annotations

from typing import Any
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db
from app.exceptions.custom_exceptions import ResourceNotFoundError
from app.repositories.deal_repository import DealRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.deal import DealResponse
from app.schemas.lead import LeadConvertRequest, LeadCreate, LeadResponse, LeadUpdate
from app.services.conversion_service import ConversionService
from app.services.import_service import ImportService

router = APIRouter()


def get_lead_repository(db: Client = Depends(get_db)) -> LeadRepository:
    return LeadRepository(db)


def get_deal_repository(db: Client = Depends(get_db)) -> DealRepository:
    return DealRepository(db)


def get_import_service(db: Client = Depends(get_db)) -> ImportService:
    return ImportService(db)


def get_conversion_service(db: Client = Depends(get_db)) -> ConversionService:
    return ConversionService(db)


@router.get("/", response_model=List[LeadResponse])
async def get_leads(
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
    owner_id: UUID | None = None,
    organization_id: UUID | None = None,
    source: str | None = None,
    search: str | None = None,
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Get leads with optional filtering."""
    return await repository.list_leads(
        skip=skip,
        limit=limit,
        status=status,
        owner_id=str(owner_id) if owner_id else None,
        organization_id=str(organization_id) if organization_id else None,
        source=source,
        search=search,
    )


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: UUID,
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Get a lead by ID."""
    return await repository.get_by_id(lead_id)


@router.post("/", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Create a new lead."""
    lead_data = payload.model_dump()

    owner_id = lead_data.get("owner_id") or current_user.get("id")
    if owner_id:
        lead_data["owner_id"] = str(owner_id)

    organization_id = lead_data.get("organization_id")
    if organization_id:
        lead_data["organization_id"] = str(organization_id)

    return await repository.create(lead_data)


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Update a lead."""
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "owner_id" in update_data and update_data["owner_id"] is not None:
        update_data["owner_id"] = str(update_data["owner_id"])

    if "organization_id" in update_data and update_data["organization_id"] is not None:
        update_data["organization_id"] = str(update_data["organization_id"])

    return await repository.update_by_id(lead_id, update_data)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: UUID,
    current_user: dict = Depends(require_admin()),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Delete a lead."""
    await repository.delete_by_id(lead_id)
    return None


@router.post("/{lead_id}/convert-to-deal", response_model=DealResponse, status_code=status.HTTP_201_CREATED)
async def convert_lead_to_deal(
    lead_id: UUID,
    payload: LeadConvertRequest,
    current_user: dict = Depends(require_auth),
    service: ConversionService = Depends(get_conversion_service),
):
    """
    Convert a lead into a deal.

    Following the reference CRM pattern:
    - Creates a deal linked to the lead
    - Marks lead as converted with status="qualified"
    - Only triggers customer creation when deal status becomes "Won"
    """
    try:
        return await service.convert_lead_to_deal(
            lead_id=str(lead_id),
            stage=payload.stage or "qualified",
            value=payload.value,
            currency=payload.currency or "USD",
            expected_close_at=payload.expected_close_at,
            owner_id=str(payload.owner_id) if payload.owner_id else None,
            organization_id=str(payload.organization_id) if payload.organization_id else None,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc.detail))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/ingest", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def ingest_lead_payload(
    payload: dict[str, Any],
    current_user: dict = Depends(require_auth),
    service: ImportService = Depends(get_import_service),
):
    """Ingest a lead payload from a connected site or integration."""
    return await service.ingest_lead_payload(payload=payload)
