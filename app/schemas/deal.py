from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.sanitization import sanitize_text
from app.validators.custom_validators import validate_no_dangerous_sql_tokens


class DealBase(BaseModel):
    lead_id: Optional[UUID] = None
    owner_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    stage: Optional[str] = Field(default="prospecting", max_length=50)
    value: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default="USD", max_length=10)
    expected_close_at: Optional[datetime] = None
    lost_reason: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("stage", "currency", "lost_reason")
    @classmethod
    def validate_text_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class DealCreate(DealBase):
    pass


class DealUpdate(BaseModel):
    lead_id: Optional[UUID] = None
    owner_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    stage: Optional[str] = Field(default=None, max_length=50)
    value: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=10)
    expected_close_at: Optional[datetime] = None
    lost_reason: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("stage", "currency", "lost_reason")
    @classmethod
    def validate_text_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class DealResponse(DealBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
