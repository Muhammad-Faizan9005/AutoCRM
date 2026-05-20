from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from supabase import Client

from app.auth.dependencies import require_auth
from app.database import get_db, run_db_operation
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification import NotificationResponse

router = APIRouter()


def get_notification_repository(db: Client = Depends(get_db)) -> NotificationRepository:
    return NotificationRepository(db)


@router.get("/", response_model=List[NotificationResponse])
async def get_notifications(
    skip: int = 0,
    limit: int = 50,
    unread_only: bool = False,
    current_user: dict = Depends(require_auth),
    repository: NotificationRepository = Depends(get_notification_repository),
):
    recipient_id = str(current_user.get("id") or "")
    if not recipient_id:
        return []
    return await repository.list_for_user(
        recipient_id=recipient_id,
        skip=skip,
        limit=limit,
        unread_only=unread_only,
    )


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: NotificationRepository = Depends(get_notification_repository),
):
    existing = await repository.get_by_id(notification_id)
    if str(existing.get("recipient_id") or "") != str(current_user.get("id") or ""):
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    def _query():
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE notifications SET read_at = NOW() WHERE id = :id"),
                {"id": str(notification_id)},
            )

    await run_db_operation(_query)
    return await repository.get_by_id(notification_id)


@router.patch("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    recipient_id = str(current_user.get("id") or "")
    if not recipient_id:
        return None

    def _query():
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE notifications "
                    "SET read_at = NOW() "
                    "WHERE recipient_id = :recipient_id AND read_at IS NULL"
                ),
                {"recipient_id": recipient_id},
            )

    await run_db_operation(_query)
    return None
