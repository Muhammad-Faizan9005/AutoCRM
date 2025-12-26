from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class TicketBase(BaseModel):
    subject: str
    description: Optional[str] = None
    status: Optional[str] = "open"
    priority: Optional[str] = "medium"
    category: Optional[str] = None


class TicketCreate(TicketBase):
    customer_id: UUID


class TicketUpdate(BaseModel):
    subject: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    assigned_to: Optional[UUID] = None


class TicketResponse(TicketBase):
    id: UUID
    customer_id: UUID
    assigned_to: Optional[UUID] = None
    ai_summary: Optional[str] = None
    ai_sentiment: Optional[str] = None
    ai_suggested_response: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TicketMessageBase(BaseModel):
    content: str
    sender_type: str  # 'customer', 'agent', 'ai'


class TicketMessageCreate(TicketMessageBase):
    ticket_id: UUID
    sender_id: Optional[UUID] = None


class TicketMessageResponse(TicketMessageBase):
    id: UUID
    ticket_id: UUID
    sender_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True
