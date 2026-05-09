from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class TeamResponse(BaseModel):
    id: UUID
    name: str
    manager_id: UUID
    manager_name: Optional[str] = None
    manager_email: Optional[EmailStr] = None
    member_count: int = 0
    created_at: datetime


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=255)


class TeamList(BaseModel):
    items: List[TeamResponse]
    total: int


class TeamMemberStats(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    status: str
    role: str
    joined_at: Optional[datetime] = None
    leads_count: int = 0
    deals_count: int = 0
    tasks_open: int = 0


class TeamDetail(BaseModel):
    id: UUID
    name: str
    manager_id: UUID
    manager_name: Optional[str] = None
    manager_email: Optional[EmailStr] = None
    members: List[TeamMemberStats] = []
    created_at: datetime


class TeamMemberAdd(BaseModel):
    agent_id: UUID
