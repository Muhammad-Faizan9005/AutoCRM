from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


AdminStatus = Literal["active", "invited", "disabled"]


class AdminUserResponse(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    role: str
    status: AdminStatus
    team_id: Optional[UUID] = None


class AdminUserList(BaseModel):
    items: List[AdminUserResponse]
    total: int


class DeletedUserResponse(BaseModel):
    id: UUID
    agent_id: Optional[UUID] = None
    full_name: str
    email: EmailStr
    role: str
    status: str
    permissions: dict[str, Any] = Field(default_factory=dict)
    permission_file: Optional[str] = None
    deleted_by: Optional[UUID] = None
    deleted_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeletedUserList(BaseModel):
    items: List[DeletedUserResponse]
    total: int


class AdminUserCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    role: Literal["admin", "manager", "sales_manager", "agent", "sales_rep"] = "agent"
    status: AdminStatus = "invited"
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)
    team_id: Optional[UUID] = None  # required when admin creates a sales rep


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    email: Optional[EmailStr] = None
    role: Optional[Literal["admin", "manager", "sales_manager", "agent", "sales_rep"]] = None
    status: Optional[AdminStatus] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class AdminHighlight(BaseModel):
    label: str
    value: Union[str, int, float]
    meta: Optional[str] = None


class AdminCoverageItem(BaseModel):
    label: str
    percent: int
    value: Optional[str] = None
    meta: Optional[str] = None


class AdminWatchItem(BaseModel):
    title: str
    value: str
    note: Optional[str] = None


class AdminQueueItem(BaseModel):
    title: str
    status: str
    age: str


class AdminActivityItem(BaseModel):
    message: str
    at: datetime


class AdminActivityLogItem(BaseModel):
    id: str
    event_type: str
    entity_type: str
    entity_id: Optional[UUID] = None
    message: str
    actor_id: Optional[UUID] = None
    actor_name: Optional[str] = None
    actor_email: Optional[str] = None
    happened_at: datetime


class AdminActivityLog(BaseModel):
    items: List[AdminActivityLogItem]
    total: int


class AdminOverview(BaseModel):
    highlights: List[AdminHighlight]
    coverage: List[AdminCoverageItem]
    sources: List[AdminCoverageItem] = Field(default_factory=list)
    watchlist: List[AdminWatchItem]
    queues: List[AdminQueueItem]
    team_performance: List[AdminHighlight] = Field(default_factory=list)
    activity: List[AdminActivityItem]
