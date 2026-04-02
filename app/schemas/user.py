from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.utils.sanitization import sanitize_text
from app.validators.custom_validators import validate_person_name


RoleType = Literal["admin", "sales_manager", "sales_rep"]


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=255)
    role: RoleType = "sales_rep"

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        cleaned = sanitize_text(value)
        return validate_person_name(cleaned)


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=128)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    role: RoleType | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        return validate_person_name(cleaned)


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    role: RoleType
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
