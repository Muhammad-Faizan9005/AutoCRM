from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


AdminStatus = Literal["active", "invited", "disabled"]


class AdminUserResponse(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    role: str
    status: AdminStatus


class AdminUserList(BaseModel):
    items: List[AdminUserResponse]
    total: int


class AdminUserCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    role: str = "agent"
    status: AdminStatus = "invited"
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    status: Optional[AdminStatus] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class AdminHighlight(BaseModel):
    label: str
    value: str
    meta: Optional[str] = None


class AdminCoverageItem(BaseModel):
    label: str
    percent: int


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


class AdminOverview(BaseModel):
    highlights: List[AdminHighlight]
    coverage: List[AdminCoverageItem]
    watchlist: List[AdminWatchItem]
    queues: List[AdminQueueItem]
    activity: List[AdminActivityItem]
