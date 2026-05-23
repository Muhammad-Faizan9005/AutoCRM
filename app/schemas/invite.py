from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.utils.sanitization import sanitize_text
from app.validators.custom_validators import validate_person_name


class InviteValidationResponse(BaseModel):
    email: EmailStr
    role: str
    expires_at: datetime
    invited_by: Optional[str] = None


class InviteAcceptRequest(BaseModel):
    token: str = Field(..., min_length=16)
    full_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        cleaned = sanitize_text(value)
        return validate_person_name(cleaned)


class InviteAcceptResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    role: str
