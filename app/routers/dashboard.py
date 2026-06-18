from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_auth
from app.database import get_db, run_db_operation
from sqlalchemy import text
from app.postgres_client import PostgresClient
from app.schemas.dashboard import DashboardActivity, DashboardSummary
from app.services.dashboard_service import DashboardService

router = APIRouter()


def get_dashboard_service(db: PostgresClient = Depends(get_db)) -> DashboardService:
    return DashboardService(db)


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    days: int = 30,
    current_user: dict = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
):
    """Return high-level KPI metrics for the dashboard."""
    return await service.get_summary(current_user, trend_days=days)


@router.get("/activity", response_model=DashboardActivity)
async def get_dashboard_activity(
    days: int = 14,
    current_user: dict = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
):
    """Return activity counts grouped by day."""
    return await service.get_activity(current_user, days=days)


@router.get("/ai-summary/latest")
async def get_latest_ai_summary(
    current_user: dict = Depends(require_auth),
    db: PostgresClient = Depends(get_db),
):
    """Return the latest AI daily summary note/action for dashboard display."""
    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT n.id, n.content, n.ai_reason, n.created_at, aa.reason, ar.trigger_type "
                    "FROM notes n "
                    "LEFT JOIN ai_agent_actions aa ON aa.crm_record_id = n.id "
                    "LEFT JOIN ai_agent_runs ar ON ar.id = aa.run_id "
                    "WHERE n.source = 'ai' AND (ar.trigger_type = 'daily_summary' OR n.entity_type = 'user') "
                    "ORDER BY n.created_at DESC LIMIT 1"
                )
            ).mappings().first()
            return dict(row) if row else None
    return await run_db_operation(_query)
