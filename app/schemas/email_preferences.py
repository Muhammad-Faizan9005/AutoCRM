from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EmailPreferenceResponse(BaseModel):
    user_id: UUID
    role: str
    email_enabled: bool
    lead_assigned_enabled: bool
    task_assigned_enabled: bool
    high_priority_override: bool
    created_at: datetime
    updated_at: datetime


class EmailPreferenceUpdate(BaseModel):
    email_enabled: bool | None = None
    lead_assigned_enabled: bool | None = None
    task_assigned_enabled: bool | None = None
    high_priority_override: bool | None = None

    def any_updates(self) -> bool:
        return any(
            value is not None
            for value in (
                self.email_enabled,
                self.lead_assigned_enabled,
                self.task_assigned_enabled,
                self.high_priority_override,
            )
        )
