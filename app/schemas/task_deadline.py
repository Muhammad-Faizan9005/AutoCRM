from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskDeadlineCandidate(BaseModel):
    task_id: UUID
    title: str
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    due_at: datetime
    updated_at: datetime | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    entity_name: str | None = None
    assigned_to: UUID | None = None
    assignee_name: str | None = None
    assignee_email: str | None = None
    owner_id: UUID | None = None
    owner_name: str | None = None
    manager_id: UUID | None = None
    admin_ids: list[UUID] = Field(default_factory=list)
    deadline_state: str
    severity: str
    is_customer_facing: bool = False
    should_use_llm: bool = False
    hours_until_due: float | None = None
    hours_overdue: float | None = None
    llm_cache_key: str
    context_hash: str
    fresh_llm_output: str | None = None
    fallback_used: bool = False

    model_config = ConfigDict(from_attributes=True)


class TaskDeadlineCandidateList(BaseModel):
    items: list[TaskDeadlineCandidate]


class TaskDeadlineAlertIn(BaseModel):
    task_id: UUID
    alert_type: str = Field(..., max_length=80)
    severity: str = Field(..., max_length=30)
    recipient_id: UUID | None = None
    message: str | None = None
    llm_cache_key: str | None = None
    llm_output: str | None = None
    fallback_used: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskDeadlineAlertResponse(BaseModel):
    id: UUID | None = None
    created: bool
    dedupe_key: str

