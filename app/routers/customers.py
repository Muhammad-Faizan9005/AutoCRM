from fastapi import APIRouter, HTTPException, Depends
from typing import List
from uuid import UUID
from supabase import Client

from app.database import get_db
from app.repositories.customer_repository import CustomerRepository
from app.schemas.customer import CustomerCreate, CustomerUpdate, CustomerResponse, CustomerStatus
from app.auth.dependencies import require_admin, require_auth

router = APIRouter()


def get_customer_repository(db: Client = Depends(get_db)) -> CustomerRepository:
    return CustomerRepository(db)


@router.get("/", response_model=List[CustomerResponse])
async def get_customers(
    skip: int = 0,
    limit: int = 100,
    status: CustomerStatus | None = None,
    current_user: dict = Depends(require_auth),
    repository: CustomerRepository = Depends(get_customer_repository),
):
    """Get all customers with optional filtering"""
    return await repository.list_customers(skip=skip, limit=limit, status=status)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: UUID,
    current_user: dict = Depends(require_auth),
    repository: CustomerRepository = Depends(get_customer_repository),
):
    """Get a specific customer by ID"""
    return await repository.get_by_id(customer_id)


@router.post("/", response_model=CustomerResponse, status_code=201)
async def create_customer(
    customer: CustomerCreate,
    current_user: dict = Depends(require_auth),
    repository: CustomerRepository = Depends(get_customer_repository),
):
    """Create a new customer"""
    return await repository.create(customer.model_dump())


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: UUID,
    customer: CustomerUpdate,
    current_user: dict = Depends(require_auth),
    repository: CustomerRepository = Depends(get_customer_repository),
):
    """Update a customer"""
    update_data = customer.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

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
