from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.sanitization import sanitize_text
from app.validators.custom_validators import validate_no_dangerous_sql_tokens


class CallSessionBase(BaseModel):
    lead_id: UUID
    direction: str = Field(default="outbound", max_length=20)
    status: Optional[str] = Field(default="created", max_length=20)
    outcome: Optional[str] = Field(default=None, max_length=100)

    @field_validator("direction", "status")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned

    @field_validator("outcome")
    @classmethod
    def validate_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class CallStartRequest(BaseModel):
    lead_id: UUID
    direction: Optional[str] = Field(default="outbound", max_length=20)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class CallSessionResponse(CallSessionBase):
    id: UUID
    initiated_by: Optional[UUID] = None
    room_id: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    recording_path: Optional[str] = None
    recording_mime: Optional[str] = None
    recording_size: Optional[int] = None
    transcript: Optional[str] = None
    meeting_summary: Optional[str] = None
    processing_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CallStartResponse(BaseModel):
    call: CallSessionResponse
    room_token: str
    invite_token: str
    invite_url: str


class CallRecordingResponse(BaseModel):
    call_id: UUID
    recording_url: str
    recording_path: str
    recording_mime: Optional[str] = None
    recording_size: Optional[int] = None
