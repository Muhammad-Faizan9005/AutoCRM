from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime
from uuid import UUID


TicketStatus = Literal["open", "in_progress", "pending", "resolved", "closed"]
TicketPriority = Literal["low", "medium", "high", "urgent"]
TicketSenderType = Literal["customer", "agent", "ai"]


class TicketBase(BaseModel):
    subject: str
    description: Optional[str] = None
    status: Optional[TicketStatus] = "open"
    priority: Optional[TicketPriority] = "medium"
    category: Optional[str] = None


class TicketCreate(TicketBase):
    customer_id: UUID


class TicketUpdate(BaseModel):
    subject: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
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
    sender_type: TicketSenderType


class TicketMessageCreate(TicketMessageBase):
    sender_id: Optional[UUID] = None


class TicketMessageResponse(TicketMessageBase):
    id: UUID
    ticket_id: UUID
    sender_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True
