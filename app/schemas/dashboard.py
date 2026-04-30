from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class StageStat(BaseModel):
    stage: str
    count: int
    value_total: Optional[float] = None


class StatusStat(BaseModel):
    status: str
    count: int


class DashboardSummary(BaseModel):
    leads_total: int
    deals_total: int
    organizations_total: int
    tasks_total: int
    notes_total: int
    revenue_total: float
    pipeline: list[StageStat]
    leads_by_status: list[StatusStat]
    tasks_by_status: list[StatusStat]


class ActivityPoint(BaseModel):
    day: date
    leads: int
    deals: int
    tasks: int
    notes: int


class DashboardActivity(BaseModel):
    days: int
    series: list[ActivityPoint]
