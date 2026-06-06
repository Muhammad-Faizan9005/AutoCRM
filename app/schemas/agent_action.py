from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
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
    requires_approval: Optional[bool] = None
    approval_status: Optional[str] = Field(default=None, max_length=50)

    @field_validator("action_type", "entity_type", "reason")
    @classmethod
    def validate_text(cls, value: str) -> str:
        cleaned = sanitize_text(value)
        validate_no_dangerous_sql_tokens(cleaned)
        return cleaned


class AgentRunCreate(BaseModel):
    external_run_id: Optional[UUID] = None
    trigger_type: str = Field(..., min_length=1, max_length=100)
    entity_id: UUID
    entity_type: str = Field(..., min_length=1, max_length=50)
    status: str = Field(default="running", max_length=50)
    event_payload: dict[str, Any] = Field(default_factory=dict)


class AgentTraceCreate(BaseModel):
    step: str = Field(..., min_length=1, max_length=100)
    status: str = Field(default="completed", max_length=50)
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentApprovalDecision(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


class AgentActionResponse(BaseModel):
    status: Literal["created", "pending_approval", "rejected"]
    action_type: str
    action_id: str
    id: Optional[str] = None
    approval_id: Optional[str] = None


class AgentRunResponse(BaseModel):
    id: UUID
    external_run_id: Optional[UUID] = None
    trigger_type: str
    entity_id: UUID
    entity_type: str
    status: str
    summary: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class AgentSettingUpdate(BaseModel):
    enabled: bool


class AgentSettingResponse(BaseModel):
    id: Optional[UUID] = None
    agent_type: str
    enabled: bool
    updated_by: Optional[UUID] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# AI Agents Registry schemas
# ---------------------------------------------------------------------------

class AiAgentResponse(BaseModel):
    id: UUID
    agent_key: str
    display_name: str
    description: Optional[str] = None
    agent_type: str
    status: str
    enabled: bool
    capabilities: list[str] = []
    config: dict = {}
    service_url: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Runtime stats — populated by the endpoint, not stored in the table
    total_runs: int = 0
    total_actions: int = 0
    pending_actions: int = 0


class AiAgentUpdate(BaseModel):
    enabled: Optional[bool] = None
    status: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=500)
    service_url: Optional[str] = Field(default=None, max_length=500)
    config: Optional[dict] = None


class AiAgentCredentialCreate(BaseModel):
    scopes: list[str] = Field(
        default=["runs:create", "runs:read", "traces:create", "actions:create", "actions:read", "settings:read"]
    )
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=3650)


class AiAgentCredentialResponse(BaseModel):
    id: UUID
    ai_agent_id: UUID
    key_prefix: str
    scopes: list[str] = []
    is_active: bool
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    # Only returned once, on creation
    raw_token: Optional[str] = None
