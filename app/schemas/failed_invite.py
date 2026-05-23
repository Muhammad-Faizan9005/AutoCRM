from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FailedInviteResponse(BaseModel):
    id: UUID
    agent_id: UUID | None = None
    email: str
    full_name: str | None = None
    role: str
    team_id: UUID | None = None
    invited_by: UUID | None = None
    reason: str
    failed_at: datetime
    created_at: datetime
