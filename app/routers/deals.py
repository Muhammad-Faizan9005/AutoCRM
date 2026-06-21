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
from app.utils.team_access import can_access_lead, can_access_rep

router = APIRouter()

DEAL_TYPES = {"new_business", "upsell", "renewal", "cross_sell"}


def _normalize_deal_type(value: str | None) -> str:
    normalized = (value or "new_business").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"new", "new_sale", "new_business_sale"}:
        normalized = "new_business"
    if normalized in {"crosssell", "cross_selling"}:
        normalized = "cross_sell"
    if normalized not in DEAL_TYPES:
        raise ValueError("Invalid deal_type. Use new_business, upsell, renewal, or cross_sell")
    return normalized


def _normalize_deal_status(value: str | None) -> str | None:
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


async def _get_lead_owner_for_deal(db: Client, lead_id: str | None) -> str | None:
    if not lead_id:
        return None

    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT owner_id FROM leads WHERE id = :lead_id"),
                {"lead_id": lead_id},
            ).mappings().first()
            return str(row.get("owner_id")) if row and row.get("owner_id") else None

    return await run_db_operation(_query)


async def _can_access_deal(db: Client, current_user: dict, deal: dict) -> bool:
    if await can_access_rep(db, current_user, str(deal.get("owner_id") or "")):
        return True
    lead_id = str(deal.get("lead_id") or "")
    if lead_id and await can_access_lead(db, current_user, lead_id):
        return True
    return False


async def _list_deals_workspace(
    db: Client,
    current_user: dict,
    *,
    skip: int = 0,
    limit: int = 100,
    stage: str | None = None,
    owner_id: UUID | None = None,
    organization_id: UUID | None = None,
    lead_id: UUID | None = None,
) -> list[dict[str, Any]]:
    role = str(current_user.get("role") or "").strip().lower()
    requester_id = str(current_user.get("id") or "")

    if owner_id is not None and not await can_access_rep(db, current_user, str(owner_id)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    def _query():
        with db.engine.connect() as conn:
            sql = (
                "SELECT DISTINCT d.*, "
                "l.name AS lead_name, l.company AS lead_company, "
                "o.name AS organization_name, "
                "a.full_name AS owner_name, a.email AS owner_email "
                "FROM deals d "
                "LEFT JOIN leads l ON l.id = d.lead_id "
                "LEFT JOIN organizations o ON o.id = d.organization_id "
                "LEFT JOIN agents a ON a.id = d.owner_id "
            )
            params: dict[str, Any] = {}
            where_clauses: list[str] = []

            if role in {"manager", "sales_manager"} and owner_id is None:
                sql += (
                    "LEFT JOIN team_members tm_deal ON tm_deal.agent_id = d.owner_id "
                    "LEFT JOIN teams team_deal ON team_deal.id = tm_deal.team_id "
                    "LEFT JOIN team_members tm_lead ON tm_lead.agent_id = l.owner_id "
                    "LEFT JOIN teams team_lead ON team_lead.id = tm_lead.team_id "
                )
                where_clauses.append("(team_deal.manager_id = :mid OR team_lead.manager_id = :mid)")
                params["mid"] = requester_id
            elif role not in {"admin", "manager", "sales_manager"} and owner_id is None:
                where_clauses.append("(d.owner_id = :uid OR l.owner_id = :uid)")
                params["uid"] = requester_id
            elif owner_id is not None:
                where_clauses.append("d.owner_id = :owner_id")
                params["owner_id"] = str(owner_id)

            if stage:
                where_clauses.append("d.stage = :stage")
                params["stage"] = stage
            if organization_id:
                where_clauses.append("d.organization_id = :org_id")
                params["org_id"] = str(organization_id)
            if lead_id:
                where_clauses.append("d.lead_id = :lead_id")
                params["lead_id"] = str(lead_id)

            if where_clauses:
                sql += "WHERE " + " AND ".join(where_clauses) + " "

            sql += "ORDER BY d.created_at DESC OFFSET :skip LIMIT :limit"
            params["skip"] = skip
            params["limit"] = limit
            rows = conn.execute(text(sql), params).mappings().all()
            return [dict(row) for row in rows]

    return await run_db_operation(_query)


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
                    "SELECT DISTINCT d.* FROM deals d "
                    "LEFT JOIN leads l ON l.id = d.lead_id "
                    "LEFT JOIN team_members tm_deal ON tm_deal.agent_id = d.owner_id "
                    "LEFT JOIN teams team_deal ON team_deal.id = tm_deal.team_id "
                    "LEFT JOIN team_members tm_lead ON tm_lead.agent_id = l.owner_id "
                    "LEFT JOIN teams team_lead ON team_lead.id = tm_lead.team_id "
                    "WHERE (team_deal.manager_id = :mid OR team_lead.manager_id = :mid) "
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

    if role not in {"admin", "manager", "sales_manager"} and owner_id is None:
        def _query_rep_deals():
            with db.engine.connect() as conn:
                sql = (
                    "SELECT DISTINCT d.* FROM deals d "
                    "LEFT JOIN leads l ON l.id = d.lead_id "
                    "WHERE (d.owner_id = :uid OR l.owner_id = :uid) "
                )
                params: dict[str, Any] = {"uid": requester_id}
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

        return await run_db_operation(_query_rep_deals)

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


@router.get("/workspace")
async def get_deals_workspace(
    skip: int = 0,
    limit: int = 100,
    stage: str | None = None,
    owner_id: UUID | None = None,
    organization_id: UUID | None = None,
    lead_id: UUID | None = None,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    return await _list_deals_workspace(
        db,
        current_user,
        skip=skip,
        limit=limit,
        stage=stage,
        owner_id=owner_id,
        organization_id=organization_id,
        lead_id=lead_id,
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
    if not await _can_access_deal(db, current_user, deal):
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
    try:
        deal_data["deal_type"] = _normalize_deal_type(deal_data.get("deal_type"))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    owner_id = deal_data.get("owner_id")
    if not owner_id and deal_data.get("lead_id"):
        owner_id = await _get_lead_owner_for_deal(db, str(deal_data.get("lead_id")))
    owner_id = owner_id or current_user.get("id")
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
        new_status=created.get("status") or deal_data.get("status") or "qualified",
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
    if not await _can_access_deal(db, current_user, existing):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    for key in ("lead_id", "owner_id", "organization_id", "customer_id"):
        if key in update_data and update_data[key] is not None:
            update_data[key] = str(update_data[key])
    if "owner_id" in update_data and update_data["owner_id"] is not None:
        await _assert_deal_assignment_permissions(db, current_user, update_data["owner_id"])
    if "deal_type" in update_data and update_data["deal_type"] is not None:
        try:
            update_data["deal_type"] = _normalize_deal_type(update_data["deal_type"])
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

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
