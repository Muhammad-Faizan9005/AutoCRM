from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.sanitization import sanitize_text
from app.validators.custom_validators import validate_no_dangerous_sql_tokens


class TaskBase(BaseModel):
    entity_type: str = Field(..., min_length=1, max_length=50)
    entity_id: UUID
    title: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = Field(default=None, max_length=5000)
    assigned_to: Optional[UUID] = None
    status: Optional[str] = Field(default="backlog", max_length=50)
    priority: Optional[str] = Field(default="medium", max_length=20)
    due_at: Optional[datetime] = None

    @field_validator("entity_type", "title", "status", "priority")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
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


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=255)
    description: Optional[str] = Field(default=None, max_length=5000)
    assigned_to: Optional[UUID] = None
    status: Optional[str] = Field(default=None, max_length=50)
    priority: Optional[str] = Field(default=None, max_length=20)
    due_at: Optional[datetime] = None
    entity_type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    entity_id: Optional[UUID] = None

    @field_validator("title", "status", "priority", "entity_type")
    @classmethod
    def validate_text_fields(cls, value: Optional[str]) -> Optional[str]:
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


class TaskResponse(TaskBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
