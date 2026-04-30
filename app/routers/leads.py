from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db
from app.repositories.deal_repository import DealRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.deal import DealResponse
from app.schemas.lead import LeadConvertRequest, LeadCreate, LeadResponse, LeadUpdate

router = APIRouter()


def get_lead_repository(db: Client = Depends(get_db)) -> LeadRepository:
    return LeadRepository(db)


def get_deal_repository(db: Client = Depends(get_db)) -> DealRepository:
    return DealRepository(db)


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
    lead_repository: LeadRepository = Depends(get_lead_repository),
    deal_repository: DealRepository = Depends(get_deal_repository),
):
    """Convert a lead into a deal."""
    lead = await lead_repository.get_by_id(lead_id)

    owner_id = payload.owner_id or lead.get("owner_id") or current_user.get("id")
    organization_id = payload.organization_id or lead.get("organization_id")

    deal_data = {
        "lead_id": str(lead_id),
        "owner_id": str(owner_id) if owner_id else None,
        "organization_id": str(organization_id) if organization_id else None,
        "stage": payload.stage or "qualified",
        "value": payload.value,
        "currency": payload.currency or "USD",
        "expected_close_at": payload.expected_close_at,
    }

    created_deal = await deal_repository.create(deal_data)
    await lead_repository.update_by_id(lead_id, {"status": "converted"})

    return created_deal
