from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal, Optional
from datetime import datetime
from uuid import UUID

from app.utils.sanitization import sanitize_text
from app.validators.custom_validators import validate_no_dangerous_sql_tokens


TicketStatus = Literal["open", "in_progress", "pending", "resolved", "closed"]
TicketPriority = Literal["low", "medium", "high", "urgent"]
TicketSenderType = Literal["customer", "agent", "ai"]


class TicketBase(BaseModel):
    subject: str = Field(..., min_length=3, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[TicketStatus] = "open"
    priority: Optional[TicketPriority] = "medium"
    category: Optional[str] = Field(default=None, min_length=2, max_length=100)

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class TicketCreate(TicketBase):
    customer_id: UUID


class TicketUpdate(BaseModel):
    subject: Optional[str] = Field(default=None, min_length=3, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    category: Optional[str] = Field(default=None, min_length=2, max_length=100)
    assigned_to: Optional[UUID] = None

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


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

    model_config = ConfigDict(from_attributes=True)


class TicketMessageBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    sender_type: TicketSenderType

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class TicketMessageCreate(TicketMessageBase):
    sender_id: Optional[UUID] = None


class TicketMessageResponse(TicketMessageBase):
    id: UUID
    ticket_id: UUID
    sender_id: Optional[UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
