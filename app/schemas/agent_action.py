from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.utils.sanitization import sanitize_text
from app.validators.custom_validators import validate_no_dangerous_sql_tokens


class AgentActionIn(BaseModel):
    action_type: str = Field(..., min_length=1, max_length=50)
    entity_type: str = Field(..., min_length=1, max_length=50)
    entity_id: UUID
    reason: str = Field(..., min_length=1, max_length=500)
    data: dict[str, Any]
    idempotency_key: Optional[str] = Field(default=None, max_length=64)
    run_id: Optional[str] = None

    @field_validator("action_type", "entity_type", "reason")
    @classmethod
    def validate_text(cls, value: str) -> str:
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned
