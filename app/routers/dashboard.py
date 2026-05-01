from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_auth
from app.database import get_db
from app.postgres_client import PostgresClient
from app.schemas.dashboard import DashboardActivity, DashboardSummary
from app.services.dashboard_service import DashboardService

router = APIRouter()


def get_dashboard_service(db: PostgresClient = Depends(get_db)) -> DashboardService:
    return DashboardService(db)


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    current_user: dict = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
):
    """Return high-level KPI metrics for the dashboard."""
    return await service.get_summary()


@router.get("/activity", response_model=DashboardActivity)
async def get_dashboard_activity(
    days: int = 14,
    current_user: dict = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
):
    """Return activity counts grouped by day."""
    return await service.get_activity(days=days)
