from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db
from app.exceptions.custom_exceptions import ResourceNotFoundError
from app.repositories.deal_repository import DealRepository
from app.schemas.customer import CustomerResponse
from app.schemas.deal import DealCreate, DealResponse, DealUpdate
from app.services.conversion_service import ConversionService

router = APIRouter()


def get_deal_repository(db: Client = Depends(get_db)) -> DealRepository:
    return DealRepository(db)


def get_conversion_service(db: Client = Depends(get_db)) -> ConversionService:
    return ConversionService(db)


@router.get("/", response_model=List[DealResponse])
async def get_deals(
    skip: int = 0,
    limit: int = 100,
    stage: str | None = None,
    owner_id: UUID | None = None,
    organization_id: UUID | None = None,
    lead_id: UUID | None = None,
    current_user: dict = Depends(require_auth),
    repository: DealRepository = Depends(get_deal_repository),
):
    """Get deals with optional filtering."""
    return await repository.list_deals(
        skip=skip,
        limit=limit,
        stage=stage,
        owner_id=str(owner_id) if owner_id else None,
        organization_id=str(organization_id) if organization_id else None,
        lead_id=str(lead_id) if lead_id else None,
    )


@router.get("/{deal_id}", response_model=DealResponse)
async def get_deal(
    deal_id: UUID,
    current_user: dict = Depends(require_auth),
    repository: DealRepository = Depends(get_deal_repository),
):
    """Get a deal by ID."""
    return await repository.get_by_id(deal_id)


@router.post("/", response_model=DealResponse, status_code=status.HTTP_201_CREATED)
async def create_deal(
    payload: DealCreate,
    current_user: dict = Depends(require_auth),
    repository: DealRepository = Depends(get_deal_repository),
):
    """Create a new deal."""
    deal_data = payload.model_dump()

    owner_id = deal_data.get("owner_id") or current_user.get("id")
    if owner_id:
        deal_data["owner_id"] = str(owner_id)

    for key in ("lead_id", "organization_id"):
        if deal_data.get(key):
            deal_data[key] = str(deal_data[key])

    return await repository.create(deal_data)


@router.patch("/{deal_id}", response_model=DealResponse)
async def update_deal(
    deal_id: UUID,
    payload: DealUpdate,
    current_user: dict = Depends(require_auth),
    repository: DealRepository = Depends(get_deal_repository),
    service: ConversionService = Depends(get_conversion_service),
):
    """
    Update a deal.
    
    Special handling for status updates:
    - When status changes to "won", automatically converts deal to customer
    - Sets closed_at timestamp for terminal statuses (won, lost)
    """
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    for key in ("lead_id", "owner_id", "organization_id", "customer_id"):
        if key in update_data and update_data[key] is not None:
            update_data[key] = str(update_data[key])

    # If status is being updated, use the conversion service to handle status transitions
    if "status" in update_data:
        try:
            return await service.update_deal_status(deal_id=str(deal_id), new_status=update_data["status"])
        except ResourceNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc.detail))
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # For other updates, use the repository directly
    return await repository.update_by_id(deal_id, update_data)


@router.post("/{deal_id}/convert-to-customer", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def convert_deal_to_customer(
    deal_id: UUID,
    current_user: dict = Depends(require_auth),
    service: ConversionService = Depends(get_conversion_service),
):
    """
    Convert a deal to a customer.

    Following the reference CRM pattern:
    - Only allowed when deal status = "won"
    - Creates a customer record linked back to the deal
    - Sets deal.closed_at timestamp
    
    Can be triggered manually or automatically via status update.
    """
    try:
        return await service.convert_deal_to_customer(deal_id=str(deal_id))
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc.detail))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal(
    deal_id: UUID,
    current_user: dict = Depends(require_admin()),
    repository: DealRepository = Depends(get_deal_repository),
):
    """Delete a deal."""
    await repository.delete_by_id(deal_id)
    return None
