from fastapi import APIRouter, HTTPException, Depends
from typing import List
from uuid import UUID
from supabase import Client

from app.database import get_db
from app.repositories.customer_repository import CustomerRepository
from app.schemas.customer import CustomerCreate, CustomerUpdate, CustomerResponse, CustomerStatus
from app.auth.dependencies import require_admin, require_auth
from app.utils.team_access import can_access_customer_record, can_assign_owned_record, get_agent_team_id

router = APIRouter()


def get_customer_repository(db: Client = Depends(get_db)) -> CustomerRepository:
    return CustomerRepository(db)


async def _assert_customer_access(db: Client, current_user: dict, customer: dict) -> None:
    if await can_access_customer_record(
        db,
        current_user,
        customer_id=str(customer.get("id") or ""),
        owner_id=str(customer.get("owner_id")) if customer.get("owner_id") else None,
        team_id=str(customer.get("team_id")) if customer.get("team_id") else None,
    ):
        return
    raise HTTPException(status_code=403, detail="Insufficient permissions")


async def _prepare_customer_ownership(
    db: Client,
    current_user: dict,
    payload: dict,
    *,
    default_owner: bool,
) -> dict:
    owner_id = payload.get("owner_id")
    team_id = payload.get("team_id")

    if default_owner and owner_id is None and team_id is None:
        owner_id = current_user.get("id")
        payload["owner_id"] = str(owner_id) if owner_id else None

    if owner_id is not None:
        payload["owner_id"] = str(owner_id)
    if team_id is not None:
        payload["team_id"] = str(team_id)

    if not await can_assign_owned_record(
        db,
        current_user,
        owner_id=payload.get("owner_id"),
        team_id=payload.get("team_id"),
    ):
        raise HTTPException(status_code=403, detail="Insufficient permissions to assign customer")

    if payload.get("owner_id") and not payload.get("team_id"):
        payload["team_id"] = await get_agent_team_id(db, payload["owner_id"])

    return payload


@router.get("/", response_model=List[CustomerResponse])
async def get_customers(
    skip: int = 0,
    limit: int = 100,
    status: CustomerStatus | None = None,
    current_user: dict = Depends(require_auth),
    repository: CustomerRepository = Depends(get_customer_repository),
):
    """Get all customers with optional filtering"""
    return await repository.list_customers_for_user(
        current_user=current_user,
        skip=skip,
        limit=limit,
        status=status,
    )


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: UUID,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: CustomerRepository = Depends(get_customer_repository),
):
    """Get a specific customer by ID"""
    customer = await repository.get_by_id(customer_id)
    await _assert_customer_access(db, current_user, customer)
    return customer


@router.post("/", response_model=CustomerResponse, status_code=201)
async def create_customer(
    customer: CustomerCreate,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: CustomerRepository = Depends(get_customer_repository),
):
    """Create a new customer"""
    payload = await _prepare_customer_ownership(db, current_user, customer.model_dump(), default_owner=True)
    return await repository.create(payload)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: UUID,
    customer: CustomerUpdate,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: CustomerRepository = Depends(get_customer_repository),
):
    """Update a customer"""
    existing = await repository.get_by_id(customer_id)
    await _assert_customer_access(db, current_user, existing)
    update_data = customer.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "owner_id" in update_data or "team_id" in update_data:
        update_data = await _prepare_customer_ownership(db, current_user, update_data, default_owner=False)

    return await repository.update_by_id(customer_id, update_data)


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: UUID,
    current_user: dict = Depends(require_admin()),
    repository: CustomerRepository = Depends(get_customer_repository),
):
    """Delete a customer"""
    await repository.delete_by_id(customer_id)
    return None
