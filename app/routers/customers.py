from fastapi import APIRouter, HTTPException, Depends
from typing import List
from uuid import UUID
from supabase import Client

from app.database import get_db, run_db_operation
from app.schemas.customer import CustomerCreate, CustomerUpdate, CustomerResponse, CustomerStatus
from app.auth.dependencies import require_admin, require_auth

router = APIRouter()


@router.get("/", response_model=List[CustomerResponse])
async def get_customers(
    skip: int = 0,
    limit: int = 100,
    status: CustomerStatus | None = None,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db)
):
    """Get all customers with optional filtering"""
    query = db.table("customers").select("*")
    
    if status:
        query = query.eq("status", status)
    
    response = await run_db_operation(lambda: query.range(skip, skip + limit - 1).execute())
    return response.data


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: UUID,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db)
):
    """Get a specific customer by ID"""
    response = await run_db_operation(
        lambda: db.table("customers").select("*").eq("id", str(customer_id)).execute()
    )
    
    if not response.data:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    return response.data[0]


@router.post("/", response_model=CustomerResponse, status_code=201)
async def create_customer(
    customer: CustomerCreate,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db)
):
    """Create a new customer"""
    response = await run_db_operation(lambda: db.table("customers").insert(customer.model_dump()).execute())
    
    if not response.data:
        raise HTTPException(status_code=400, detail="Failed to create customer")
    
    return response.data[0]


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: UUID,
    customer: CustomerUpdate,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db)
):
    """Update a customer"""
    update_data = customer.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    response = await run_db_operation(
        lambda: db.table("customers").update(update_data).eq("id", str(customer_id)).execute()
    )
    
    if not response.data:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    return response.data[0]


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: UUID,
    current_user: dict = Depends(require_admin()),
    db: Client = Depends(get_db)
):
    """Delete a customer"""
    response = await run_db_operation(
        lambda: db.table("customers").delete().eq("id", str(customer_id)).execute()
    )
    
    if not response.data:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    return None
