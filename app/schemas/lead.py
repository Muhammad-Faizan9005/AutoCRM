from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.utils.sanitization import sanitize_text
from app.validators.custom_validators import validate_no_dangerous_sql_tokens, validate_phone


class LeadBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=20)
    company: Optional[str] = Field(default=None, max_length=255)
    source: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = Field(default="new", max_length=50)
    score: Optional[int] = Field(default=None, ge=0, le=100)
    score_reason: Optional[str] = Field(default=None, max_length=1000)
    converted: Optional[bool] = Field(default=False)
    owner_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned

    @field_validator("phone")
    @classmethod
    def validate_phone_number(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        return validate_phone(cleaned)

    @field_validator("company", "source", "status", "score_reason")
    @classmethod
    def validate_text_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=20)
    company: Optional[str] = Field(default=None, max_length=255)
    source: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = Field(default=None, max_length=50)
    score: Optional[int] = Field(default=None, ge=0, le=100)
    score_reason: Optional[str] = Field(default=None, max_length=1000)
    converted: Optional[bool] = None
    owner_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned

    @field_validator("phone")
    @classmethod
    def validate_phone_number(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        return validate_phone(cleaned)

    @field_validator("company", "source", "status", "score_reason")
    @classmethod
    def validate_text_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class LeadResponse(LeadBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeadConvertRequest(BaseModel):
    stage: Optional[str] = Field(default=None, max_length=50)
    value: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=10)
    expected_close_at: Optional[datetime] = None
    owner_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None

    @field_validator("stage", "currency")
    @classmethod
    def validate_stage_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned
