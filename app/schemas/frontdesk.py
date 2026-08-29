from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field

class FrontDeskSessionCreate(BaseModel):
    channel: str = Field(default="web_chat", max_length=30)
    email: str | None = None
    name: str | None = None
    subject: str | None = None

class FrontDeskMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    direction: str = Field(default="inbound", max_length=20)

class FrontDeskSessionResponse(BaseModel):
    id: UUID
    channel: str
    status: str
    contact_type: str | None = None
    contact_id: UUID | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    lead_owner_id: UUID | None = None
    lead_owner_name: str | None = None
    lead_name: str | None = None
    intent: str | None = None
    urgency: str | None = None
    handoff_reason: str | None = None
    mode: str = "frontdesk"
    discovery_stage: str = "greeting"
    identity_status: str = "unknown"
    identity_confidence: float | None = None
    handoff_status: str | None = None
    handoff_assigned_to: UUID | None = None
    # The rep-facing grace period: the UI shows how long is left to join live.
    handoff_wait_until: datetime | None = None
    handoff_notified_at: datetime | None = None
    closed_at: datetime | None = None
    summary: str | None = None
    discovery_facts: dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

class FrontDeskMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    direction: str
    content: str
    sender_type: str
    created_at: datetime

class FrontDeskSessionDetail(FrontDeskSessionResponse):
    messages: list[FrontDeskMessageResponse] = []
    ai_state: dict[str, Any] = {}

class FrontDeskHandoffRequest(BaseModel):
    reason: str = Field(..., min_length=2, max_length=500)
    intent: str | None = None
    urgency: str = Field(default="normal", max_length=20)

class FrontDeskBookingRequest(BaseModel):
    starts_at: datetime
    ends_at: datetime
    title: str = Field(default="Front-desk meeting", max_length=255)
    notes: str | None = Field(default=None, max_length=5000)

class FrontDeskIdentityRequest(BaseModel):
    email: str | None = None
    phone: str | None = None
    name: str | None = None
    company: str | None = None

class FrontDeskDiscoveryFactsRequest(BaseModel):
    facts: dict[str, Any] = Field(default_factory=dict)
    stage: str | None = None

class FrontDeskHandoffAction(BaseModel):
    reason: str = Field(..., min_length=2, max_length=1000)
    summary: str | None = Field(default=None, max_length=5000)
    urgency: str = Field(default="normal", max_length=20)

# ---------------------------------------------------------------------------
# Public (customer-facing) contracts
# ---------------------------------------------------------------------------

class PublicSessionCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    consent: bool = Field(..., description="Visitor must accept the privacy notice before chatting")

class PublicSessionResponse(BaseModel):
    session_id: UUID
    visitor_token: str
    channel: str = "web_chat_public"
    contact_name: str | None = None
    contact_email: str | None = None
    status: str = "active"
    summary: str | None = None
    created_at: datetime

class PublicMessageResponse(BaseModel):
    id: UUID
    direction: str
    sender_type: str
    content: str
    created_at: datetime

class PublicSessionDetail(BaseModel):
    session_id: UUID
    channel: str
    status: str
    contact_name: str | None = None
    contact_email: str | None = None
    summary: str | None = None
    messages: list[PublicMessageResponse] = []
    created_at: datetime

# ---------------------------------------------------------------------------
# Internal contracts (AI service -> backend, service-token authenticated)
# ---------------------------------------------------------------------------

class InternalStateUpdate(BaseModel):
    """Persist the AI service runtime state; backend is the durable source of truth."""
    state: dict[str, Any] = Field(..., max_length=100)
    stage: str | None = Field(default=None, max_length=40)
    summary: str | None = Field(default=None, max_length=5000)
    facts: dict[str, Any] = Field(default_factory=dict, max_length=100)

class InternalLeadUpsert(BaseModel):
    session_id: UUID
    name: str = Field(..., min_length=2, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=255)
    source: str = Field(default="frontdesk_chat", max_length=100)
    suggested_owner_id: UUID | None = None

class InternalTaskCreate(BaseModel):
    session_id: UUID
    lead_id: UUID | None = None
    title: str = Field(..., min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due_at: datetime | None = None
    suggested_assignee_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=120)

class InternalNoteCreate(BaseModel):
    session_id: UUID
    lead_id: UUID | None = None
    content: str = Field(..., min_length=1, max_length=5000)

class InternalHandoffCreate(BaseModel):
    session_id: UUID
    reason: str = Field(..., min_length=2, max_length=1000)
    summary: str | None = Field(default=None, max_length=5000)
    urgency: Literal["low", "normal", "high", "urgent"] = "normal"
    intent: str | None = Field(default=None, max_length=80)
    suggested_assignee_id: UUID | None = None

class InternalMeeting(BaseModel):
    provider: str = Field(default="internal", max_length=30)
    uid: str | None = Field(default=None, max_length=255)
    starts_at: datetime
    ends_at: datetime
    meeting_url: str | None = Field(default=None, max_length=2000)
    title: str = Field(default="Discovery meeting", max_length=255)
    time_zone: str | None = Field(default=None, max_length=64)

class InternalRequestedTask(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    priority: Literal["low", "medium", "high", "urgent"] = "high"
    due_at: datetime | None = None

class InternalAppointmentCreate(BaseModel):
    session_id: UUID
    lead_id: UUID | None = None
    meeting: InternalMeeting
    summary: str | None = Field(default=None, max_length=5000)
    requested_task: InternalRequestedTask | None = None
    suggested_assignee_id: UUID | None = None
