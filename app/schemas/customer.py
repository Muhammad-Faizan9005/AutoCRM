from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from typing import Literal, Optional
from datetime import datetime
from uuid import UUID

from app.utils.sanitization import sanitize_text
from app.validators.custom_validators import (
    validate_no_dangerous_sql_tokens,
    validate_person_name,
    validate_phone,
)


CustomerStatus = Literal["active", "inactive", "lead", "churned"]


class CustomerBase(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=20)
    company: Optional[str] = Field(default=None, min_length=2, max_length=255)
    status: Optional[CustomerStatus] = "active"
    notes: Optional[str] = Field(default=None, max_length=5000)
    owner_id: Optional[UUID] = None
    team_id: Optional[UUID] = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        cleaned = sanitize_text(value)
        return validate_person_name(cleaned)

    @field_validator("phone")
    @classmethod
    def validate_customer_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        return validate_phone(cleaned)

    @field_validator("company")
    @classmethod
    def validate_company(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=20)
    company: Optional[str] = Field(default=None, min_length=2, max_length=255)
    status: Optional[CustomerStatus] = None
    notes: Optional[str] = Field(default=None, max_length=5000)
    owner_id: Optional[UUID] = None
    team_id: Optional[UUID] = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        return validate_person_name(cleaned)

    @field_validator("phone")
    @classmethod
    def validate_customer_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        return validate_phone(cleaned)

    @field_validator("company")
    @classmethod
    def validate_company(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class CustomerResponse(CustomerBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
