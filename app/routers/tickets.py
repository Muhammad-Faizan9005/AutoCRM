from fastapi import APIRouter, HTTPException, Depends
from typing import List
from uuid import UUID
from supabase import Client

from app.database import get_db
from app.schemas.ticket import (
    TicketCreate, TicketUpdate, TicketResponse,
    TicketMessageCreate, TicketMessageResponse
)
from app.auth.dependencies import get_current_user

router = APIRouter()


@router.get("/", response_model=List[TicketResponse])
async def get_tickets(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    priority: str = None,
    customer_id: UUID = None,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db)
):
    """Get all tickets with optional filtering"""
    query = db.table("tickets").select("*")
    
    if status:
        query = query.eq("status", status)
    if priority:
        query = query.eq("priority", priority)
    if customer_id:
        query = query.eq("customer_id", str(customer_id))
    
    response = query.order("created_at", desc=True).range(skip, skip + limit - 1).execute()
    return response.data


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db)
):
    """Get a specific ticket by ID"""
    response = db.table("tickets").select("*").eq("id", str(ticket_id)).execute()
    
    if not response.data:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return response.data[0]


@router.post("/", response_model=TicketResponse, status_code=201)
async def create_ticket(
    ticket: TicketCreate,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db)
):
    """Create a new ticket"""
    ticket_data = ticket.model_dump()
    ticket_data["customer_id"] = str(ticket_data["customer_id"])
    
    response = db.table("tickets").insert(ticket_data).execute()
    
    if not response.data:
        raise HTTPException(status_code=400, detail="Failed to create ticket")
    
    return response.data[0]


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: UUID,
    ticket: TicketUpdate,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db)
):
    """Update a ticket"""
    update_data = ticket.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    # Convert UUID to string if present
    if "assigned_to" in update_data and update_data["assigned_to"]:
        update_data["assigned_to"] = str(update_data["assigned_to"])
    
    response = db.table("tickets").update(update_data).eq("id", str(ticket_id)).execute()
    
    if not response.data:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return response.data[0]


@router.delete("/{ticket_id}", status_code=204)
async def delete_ticket(
    ticket_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db)
):
    """Delete a ticket"""
    response = db.table("tickets").delete().eq("id", str(ticket_id)).execute()
    
    if not response.data:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return None


# =============================================
# TICKET MESSAGES
# =============================================

@router.get("/{ticket_id}/messages", response_model=List[TicketMessageResponse])
async def get_ticket_messages(
    ticket_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db)
):
    """Get all messages for a ticket"""
    response = db.table("ticket_messages").select("*").eq(
        "ticket_id", str(ticket_id)
    ).order("created_at").execute()
    
    return response.data


@router.post("/{ticket_id}/messages", response_model=TicketMessageResponse, status_code=201)
async def create_ticket_message(
    ticket_id: UUID,
    message: TicketMessageCreate,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db)
):
    """Add a message to a ticket"""
    message_data = message.model_dump()
    message_data["ticket_id"] = str(ticket_id)
    
    if message_data.get("sender_id"):
        message_data["sender_id"] = str(message_data["sender_id"])
    
    response = db.table("ticket_messages").insert(message_data).execute()
    
    if not response.data:
        raise HTTPException(status_code=400, detail="Failed to create message")
    
    return response.data[0]
