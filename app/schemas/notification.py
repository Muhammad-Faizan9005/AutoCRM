from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationResponse(BaseModel):
    id: UUID
    recipient_id: UUID
    actor_id: UUID | None = None
    type: str = Field(..., max_length=50)
    title: str = Field(..., max_length=255)
    message: str
    entity_type: str | None = Field(default=None, max_length=50)
    entity_id: UUID | None = None
    read_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
