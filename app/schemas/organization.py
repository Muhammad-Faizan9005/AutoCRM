from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.sanitization import sanitize_text
from app.validators.custom_validators import validate_no_dangerous_sql_tokens, validate_phone


class OrganizationBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    website: Optional[str] = Field(default=None, max_length=255)
    industry: Optional[str] = Field(default=None, max_length=100)
    revenue: Optional[float] = Field(default=None, ge=0)
    address: Optional[str] = Field(default=None, max_length=1000)
    phone: Optional[str] = Field(default=None, max_length=20)

    @field_validator("name", "website", "industry", "address")
    @classmethod
    def validate_text_fields(cls, value: Optional[str]) -> Optional[str]:
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


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    website: Optional[str] = Field(default=None, max_length=255)
    industry: Optional[str] = Field(default=None, max_length=100)
    revenue: Optional[float] = Field(default=None, ge=0)
    address: Optional[str] = Field(default=None, max_length=1000)
    phone: Optional[str] = Field(default=None, max_length=20)

    @field_validator("name", "website", "industry", "address")
    @classmethod
    def validate_text_fields(cls, value: Optional[str]) -> Optional[str]:
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


class OrganizationResponse(OrganizationBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
