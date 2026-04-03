from fastapi import APIRouter, HTTPException, Depends
from typing import List
from uuid import UUID
from supabase import Client

from app.database import get_db
from app.repositories.ticket_repository import TicketRepository
from app.schemas.ticket import (
    TicketCreate, TicketUpdate, TicketResponse,
    TicketMessageCreate, TicketMessageResponse, TicketPriority, TicketStatus
)
from app.auth.dependencies import require_admin, require_auth

router = APIRouter()


def get_ticket_repository(db: Client = Depends(get_db)) -> TicketRepository:
    return TicketRepository(db)


@router.get("/", response_model=List[TicketResponse])
async def get_tickets(
    skip: int = 0,
    limit: int = 100,
    status: TicketStatus | None = None,
    priority: TicketPriority | None = None,
    customer_id: UUID = None,
    current_user: dict = Depends(require_auth),
    repository: TicketRepository = Depends(get_ticket_repository),
):
    """Get all tickets with optional filtering"""
    return await repository.list_tickets(
        skip=skip,
        limit=limit,
        status=status,
        priority=priority,
        customer_id=str(customer_id) if customer_id else None,
    )


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: UUID,
    current_user: dict = Depends(require_auth),
    repository: TicketRepository = Depends(get_ticket_repository),
):
    """Get a specific ticket by ID"""
    return await repository.get_by_id(ticket_id)


@router.post("/", response_model=TicketResponse, status_code=201)
async def create_ticket(
    ticket: TicketCreate,
    current_user: dict = Depends(require_auth),
    repository: TicketRepository = Depends(get_ticket_repository),
):
    """Create a new ticket"""
    ticket_data = ticket.model_dump()
    ticket_data["customer_id"] = str(ticket_data["customer_id"])
    
    return await repository.create(ticket_data)


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: UUID,
    ticket: TicketUpdate,
    current_user: dict = Depends(require_auth),
    repository: TicketRepository = Depends(get_ticket_repository),
):
    """Update a ticket"""
    update_data = ticket.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    # Convert UUID to string if present
    if "assigned_to" in update_data:
        if current_user.get("role") not in {"sales_manager", "admin"}:
            raise HTTPException(status_code=403, detail="Only sales_manager or admin can assign tickets")
        assigned_to = update_data["assigned_to"]
        update_data["assigned_to"] = str(assigned_to) if assigned_to else None
    
    return await repository.update_by_id(ticket_id, update_data)


@router.delete("/{ticket_id}", status_code=204)
async def delete_ticket(
    ticket_id: UUID,
    current_user: dict = Depends(require_admin()),
    repository: TicketRepository = Depends(get_ticket_repository),
):
    """Delete a ticket"""
    await repository.delete_by_id(ticket_id)
    return None


# =============================================
# TICKET MESSAGES
# =============================================

@router.get("/{ticket_id}/messages", response_model=List[TicketMessageResponse])
async def get_ticket_messages(
    ticket_id: UUID,
    current_user: dict = Depends(require_auth),
    repository: TicketRepository = Depends(get_ticket_repository),
):
    """Get all messages for a ticket"""
    return await repository.list_ticket_messages(str(ticket_id))


@router.post("/{ticket_id}/messages", response_model=TicketMessageResponse, status_code=201)
async def create_ticket_message(
    ticket_id: UUID,
    message: TicketMessageCreate,
    current_user: dict = Depends(require_auth),
    repository: TicketRepository = Depends(get_ticket_repository),
):
    """Add a message to a ticket"""
    message_data = message.model_dump()
    message_data["ticket_id"] = str(ticket_id)
    
    if message_data.get("sender_id"):
        message_data["sender_id"] = str(message_data["sender_id"])
    
    return await repository.create_ticket_message(message_data)
