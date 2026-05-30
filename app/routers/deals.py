from __future__ import annotations

from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db, run_db_operation
from app.exceptions.custom_exceptions import ResourceNotFoundError
from app.repositories.deal_repository import DealRepository
from app.schemas.customer import CustomerResponse
from app.schemas.deal import DealCreate, DealResponse, DealUpdate
from app.services.conversion_service import ConversionService
from app.services.status_change_log_service import StatusChangeLogService
from app.utils.statuses import DEAL_STATUSES, normalize_status
from app.utils.team_access import can_access_rep

router = APIRouter()


def _normalize_deal_status(value: str | None) -> str | None:
    if value is not None and str(value).strip().lower() == "qualified":
        value = "qualification"
    return normalize_status(value, DEAL_STATUSES)


def get_deal_repository(db: Client = Depends(get_db)) -> DealRepository:
    return DealRepository(db)


def get_conversion_service(db: Client = Depends(get_db)) -> ConversionService:
    return ConversionService(db)


def get_status_log_service(db: Client = Depends(get_db)) -> StatusChangeLogService:
    return StatusChangeLogService(db)


async def _can_manager_assign_to_rep(db: Client, manager_id: str, rep_id: str) -> bool:
    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM team_members tm "
                    "JOIN teams t ON t.id = tm.team_id "
                    "WHERE t.manager_id = :mid AND tm.agent_id = :rid LIMIT 1"
                ),
                {"mid": manager_id, "rid": rep_id},
            ).first()
            return bool(row)

    return await run_db_operation(_query)


async def _assert_deal_assignment_permissions(
    db: Client,
    current_user: dict,
    owner_id: str | None,
) -> None:
    if owner_id is None:
        return

    user_id = str(current_user.get("id") or "")
    role = str(current_user.get("role") or "").strip().lower()
    if not user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    if role == "admin":
        return
    if role in {"sales_manager", "manager"}:
        if await _can_manager_assign_to_rep(db, user_id, owner_id):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can assign deals only to your team reps",
        )
    if owner_id == user_id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to assign deal")


@router.get("/", response_model=List[DealResponse])
async def get_deals(
    skip: int = 0,
    limit: int = 100,
    stage: str | None = None,
    owner_id: UUID | None = None,
    organization_id: UUID | None = None,
    lead_id: UUID | None = None,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: DealRepository = Depends(get_deal_repository),
):
    """Get deals with optional filtering."""
    role = str(current_user.get("role") or "").strip().lower()
    requester_id = str(current_user.get("id") or "")

    if role in {"manager", "sales_manager"} and owner_id is None:
        def _query_team_deals():
            with db.engine.connect() as conn:
                sql = (
                    "SELECT d.* FROM deals d "
                    "JOIN team_members tm ON tm.agent_id = d.owner_id "
                    "JOIN teams t ON t.id = tm.team_id "
                    "WHERE t.manager_id = :mid "
                )
                params: dict[str, Any] = {"mid": requester_id}
                if stage:
                    sql += "AND d.stage = :stage "
                    params["stage"] = stage
                if organization_id:
                    sql += "AND d.organization_id = :org_id "
                    params["org_id"] = str(organization_id)
                if lead_id:
                    sql += "AND d.lead_id = :lead_id "
                    params["lead_id"] = str(lead_id)
                sql += "ORDER BY d.created_at DESC OFFSET :skip LIMIT :limit"
                params["skip"] = skip
                params["limit"] = limit
                rows = conn.execute(text(sql), params).mappings().all()
                return [dict(row) for row in rows]

        return await run_db_operation(_query_team_deals)

    if owner_id is not None and not await can_access_rep(db, current_user, str(owner_id)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    if role not in {"admin", "manager", "sales_manager"}:
        owner_id = UUID(requester_id) if requester_id else owner_id

    return await repository.list_deals(
        skip=skip,
        limit=limit,
        stage=stage,
        owner_id=str(owner_id) if owner_id else None,
        organization_id=str(organization_id) if organization_id else None,
        lead_id=str(lead_id) if lead_id else None,
    )


@router.get("/{deal_id}", response_model=DealResponse)
async def get_deal(
    deal_id: UUID,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: DealRepository = Depends(get_deal_repository),
):
    """Get a deal by ID."""
    deal = await repository.get_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    if not await can_access_rep(db, current_user, str(deal.get("owner_id") or "")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return deal


@router.post("/", response_model=DealResponse, status_code=status.HTTP_201_CREATED)
async def create_deal(
    payload: DealCreate,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: DealRepository = Depends(get_deal_repository),
    status_log_service: StatusChangeLogService = Depends(get_status_log_service),
):
    """Create a new deal."""
    deal_data = payload.model_dump()

    if "status" in deal_data and deal_data["status"] is not None:
        try:
            deal_data["status"] = _normalize_deal_status(deal_data["status"])
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    owner_id = deal_data.get("owner_id") or current_user.get("id")
    if owner_id:
        deal_data["owner_id"] = str(owner_id)
        await _assert_deal_assignment_permissions(db, current_user, deal_data["owner_id"])

    for key in ("lead_id", "organization_id"):
        if deal_data.get(key):
            deal_data[key] = str(deal_data[key])

    created = await repository.create(deal_data)
    await status_log_service.log_change(
        entity_type="deal",
        entity_id=str(created.get("id")),
        old_status=None,
        new_status=created.get("status") or deal_data.get("status") or "qualification",
        changed_by=str(current_user.get("id") or "") or None,
    )
    return created


@router.patch("/{deal_id}", response_model=DealResponse)
async def update_deal(
    deal_id: UUID,
    payload: DealUpdate,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: DealRepository = Depends(get_deal_repository),
    service: ConversionService = Depends(get_conversion_service),
):
    """
    Update a deal.
    
    Special handling for status updates:
    - When status changes to "won", automatically converts deal to customer
    - Sets closed_at timestamp for terminal statuses (won)
    """
    update_data = payload.model_dump(exclude_unset=True)
    existing = await repository.get_by_id(deal_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    if not await can_access_rep(db, current_user, str(existing.get("owner_id") or "")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    for key in ("lead_id", "owner_id", "organization_id", "customer_id"):
        if key in update_data and update_data[key] is not None:
            update_data[key] = str(update_data[key])
    if "owner_id" in update_data and update_data["owner_id"] is not None:
        await _assert_deal_assignment_permissions(db, current_user, update_data["owner_id"])

    # If status is being updated, use the conversion service to handle status transitions
    if "status" in update_data:
        try:
            try:
                update_data["status"] = _normalize_deal_status(update_data["status"])
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
            return await service.update_deal_status(
                deal_id=str(deal_id),
                new_status=update_data["status"],
                actor_id=str(current_user.get("id") or "") or None,
            )
        except ResourceNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc.detail))
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # For other updates, use the repository directly
    return await repository.update_by_id(deal_id, update_data)


@router.post("/{deal_id}/convert-to-customer", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def convert_deal_to_customer(
    deal_id: UUID,
    current_user: dict = Depends(require_auth),
    service: ConversionService = Depends(get_conversion_service),
):
    """
    Convert a deal to a customer.

    Following the reference CRM pattern:
    - Only allowed when deal status = "won"
    - Creates a customer record linked back to the deal
    - Sets deal.closed_at timestamp
    
    Can be triggered manually or automatically via status update.
    """
    try:
        return await service.convert_deal_to_customer(deal_id=str(deal_id))
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc.detail))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal(
    deal_id: UUID,
    current_user: dict = Depends(require_admin()),
    repository: DealRepository = Depends(get_deal_repository),
):
    """Delete a deal."""
    await repository.delete_by_id(deal_id)
    return None
