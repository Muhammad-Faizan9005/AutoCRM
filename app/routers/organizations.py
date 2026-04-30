from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.organization import OrganizationCreate, OrganizationResponse, OrganizationUpdate

router = APIRouter()


def get_organization_repository(db: Client = Depends(get_db)) -> OrganizationRepository:
    return OrganizationRepository(db)


@router.get("/", response_model=List[OrganizationResponse])
async def get_organizations(
    skip: int = 0,
    limit: int = 100,
    industry: str | None = None,
    search: str | None = None,
    current_user: dict = Depends(require_auth),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Get organizations with optional filtering."""
    return await repository.list_organizations(skip=skip, limit=limit, industry=industry, search=search)


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID,
    current_user: dict = Depends(require_auth),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Get an organization by ID."""
    return await repository.get_by_id(organization_id)


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    current_user: dict = Depends(require_auth),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Create a new organization."""
    return await repository.create(payload.model_dump())


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdate,
    current_user: dict = Depends(require_auth),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Update an organization."""
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    return await repository.update_by_id(organization_id, update_data)


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: UUID,
    current_user: dict = Depends(require_admin()),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Delete an organization."""
    await repository.delete_by_id(organization_id)
    return None
