from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db, run_db_operation
from app.exceptions.custom_exceptions import ResourceNotFoundError
from app.repositories.deal_repository import DealRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.deal import DealResponse
from app.schemas.lead import LeadConvertRequest, LeadCreate, LeadResponse, LeadUpdate
from app.services.conversion_service import ConversionService
from app.services.import_service import ImportService
from app.services.notification_service import NotificationService

router = APIRouter()


def get_lead_repository(db: Client = Depends(get_db)) -> LeadRepository:
    return LeadRepository(db)


def get_deal_repository(db: Client = Depends(get_db)) -> DealRepository:
    return DealRepository(db)


def get_import_service(db: Client = Depends(get_db)) -> ImportService:
    return ImportService(db)


def get_conversion_service(db: Client = Depends(get_db)) -> ConversionService:
    return ConversionService(db)


def get_notification_service(db: Client = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


def _can_manage_leads(current_user: dict) -> bool:
    role = str(current_user.get("role") or "").strip().lower()
    return role in {"admin", "sales_manager", "manager"}


async def _get_lead_profile(db: Client, lead_id: str) -> dict[str, str | None]:
    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT name, email, owner_id FROM leads WHERE id = :lead_id"),
                {"lead_id": lead_id},
            ).mappings().first()
            if not row:
                return {"name": None, "email": None, "owner_id": None}
            return {
                "name": str(row.get("name")) if row.get("name") else None,
                "email": str(row.get("email")) if row.get("email") else None,
                "owner_id": str(row.get("owner_id")) if row.get("owner_id") else None,
            }

    return await run_db_operation(_query)


async def _assert_can_view_lead(db: Client, current_user: dict, lead_id: str) -> None:
    if _can_manage_leads(current_user):
        return
    requester_id = str(current_user.get("id") or "")
    if not requester_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    profile = await _get_lead_profile(db, lead_id)
    owner_id = profile.get("owner_id")
    if not owner_id or owner_id != requester_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


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


async def _assert_lead_assignment_permissions(
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can assign leads only to your team reps")
    if owner_id == user_id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to assign lead")


@router.get("/", response_model=List[LeadResponse])
async def get_leads(
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
    owner_id: UUID | None = None,
    organization_id: UUID | None = None,
    source: str | None = None,
    search: str | None = None,
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Get leads with optional filtering."""
    if not _can_manage_leads(current_user):
        requester_id = str(current_user.get("id") or "")
        if not requester_id:
            return []
        owner_id = UUID(requester_id)

    return await repository.list_leads(
        skip=skip,
        limit=limit,
        status=status,
        owner_id=str(owner_id) if owner_id else None,
        organization_id=str(organization_id) if organization_id else None,
        source=source,
        search=search,
    )


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: UUID,
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Get a lead by ID."""
    return await repository.get_by_id(lead_id)


@router.post("/", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
    notification_service: NotificationService = Depends(get_notification_service),
):
    """Create a new lead."""
    lead_data = payload.model_dump()

    owner_id = lead_data.get("owner_id") or current_user.get("id")
    if owner_id:
        lead_data["owner_id"] = str(owner_id)
        await _assert_lead_assignment_permissions(db, current_user, lead_data["owner_id"])

    organization_id = lead_data.get("organization_id")
    if organization_id:
        lead_data["organization_id"] = str(organization_id)

    created = await repository.create(lead_data)
    actor_id = str(current_user.get("id") or "")
    if created.get("owner_id") and str(created.get("owner_id")) != actor_id:
        actor_name = await notification_service.get_agent_name(actor_id)
        await notification_service.create_notification(
            recipient_id=str(created.get("owner_id")),
            actor_id=actor_id,
            type="lead_assigned",
            title="New lead assigned",
            message=f"{actor_name or 'Manager'} assigned lead \"{created.get('name') or 'Untitled Lead'}\" to you.",
            entity_type="lead",
            entity_id=str(created.get("id")),
        )
    return created


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
    notification_service: NotificationService = Depends(get_notification_service),
):
    """Update a lead."""
    existing = await repository.get_by_id(lead_id)
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "owner_id" in update_data and update_data["owner_id"] is not None:
        update_data["owner_id"] = str(update_data["owner_id"])
        await _assert_lead_assignment_permissions(db, current_user, update_data["owner_id"])

    if "organization_id" in update_data and update_data["organization_id"] is not None:
        update_data["organization_id"] = str(update_data["organization_id"])

    updated = await repository.update_by_id(lead_id, update_data)
    previous_owner_id = str(existing.get("owner_id")) if existing.get("owner_id") else None
    next_owner_id = str(updated.get("owner_id")) if updated.get("owner_id") else None
    actor_id = str(current_user.get("id") or "")
    if next_owner_id and next_owner_id != previous_owner_id and next_owner_id != actor_id:
        actor_name = await notification_service.get_agent_name(actor_id)
        await notification_service.create_notification(
            recipient_id=next_owner_id,
            actor_id=actor_id,
            type="lead_assigned",
            title="Lead assigned to you",
            message=f"{actor_name or 'Manager'} assigned lead \"{updated.get('name') or 'Untitled Lead'}\" to you.",
            entity_type="lead",
            entity_id=str(updated.get("id")),
        )
    return updated


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: UUID,
    current_user: dict = Depends(require_admin()),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Delete a lead."""
    await repository.delete_by_id(lead_id)
    return None


@router.get("/{lead_id}/owner")
async def get_lead_owner(
    lead_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Get lead owner display name."""
    await _assert_can_view_lead(db, current_user, str(lead_id))

    def _query():
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT a.full_name, a.email "
                    "FROM leads l "
                    "LEFT JOIN agents a ON a.id = l.owner_id "
                    "WHERE l.id = :lead_id"
                ),
                {"lead_id": str(lead_id)},
            ).mappings().first()
            if not row:
                return {"name": None, "email": None}
            return {
                "name": str(row.get("full_name")) if row.get("full_name") else None,
                "email": str(row.get("email")) if row.get("email") else None,
            }

    return await run_db_operation(_query)


@router.post("/{lead_id}/convert-to-deal", response_model=DealResponse, status_code=status.HTTP_201_CREATED)
async def convert_lead_to_deal(
    lead_id: UUID,
    payload: LeadConvertRequest,
    current_user: dict = Depends(require_auth),
    service: ConversionService = Depends(get_conversion_service),
):
    """
    Convert a lead into a deal.

    Following the reference CRM pattern:
    - Creates a deal linked to the lead
    - Marks lead as converted with status="qualified"
    - Only triggers customer creation when deal status becomes "Won"
    """
    try:
        return await service.convert_lead_to_deal(
            lead_id=str(lead_id),
            stage=payload.stage or "qualified",
            value=payload.value,
            currency=payload.currency or "USD",
            expected_close_at=payload.expected_close_at,
            owner_id=str(payload.owner_id) if payload.owner_id else None,
            organization_id=str(payload.organization_id) if payload.organization_id else None,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc.detail))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{lead_id}/discard-deal", response_model=DealResponse)
async def discard_lead_deal(
    lead_id: UUID,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    service: ConversionService = Depends(get_conversion_service),
):
    """Mark the latest deal for a lead as lost (manager/admin only)."""
    if not _can_manage_leads(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    def _get_deal_id():
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id FROM deals WHERE lead_id = :lead_id "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"lead_id": str(lead_id)},
            ).mappings().first()
            return str(row.get("id")) if row else None

    deal_id = await run_db_operation(_get_deal_id)
    if not deal_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No deal found for lead")

    try:
        return await service.update_deal_status(deal_id=deal_id, new_status="lost")
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc.detail))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/ingest", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def ingest_lead_payload(
    payload: dict[str, Any],
    current_user: dict = Depends(require_auth),
    service: ImportService = Depends(get_import_service),
):
    """Ingest a lead payload from a connected site or integration."""
    return await service.ingest_lead_payload(payload=payload)


@router.get("/{lead_id}/emails")
async def get_lead_emails(
    lead_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Mock email timeline for a lead."""
    await _assert_can_view_lead(db, current_user, str(lead_id))
    profile = await _get_lead_profile(db, str(lead_id))
    lead_name = profile.get("name") or "Lead"
    lead_email = profile.get("email") or "unknown@example.com"
    now = datetime.now(timezone.utc)
    return [
        {
            "id": f"email-{lead_id}-1",
            "direction": "received",
            "subject": f"Re: {lead_name} onboarding",
            "from": lead_email,
            "to": "sales@autocrm.io",
            "sent_at": (now - timedelta(days=2, hours=3)).isoformat(),
            "snippet": "Thanks for the details, can we schedule a quick call?",
        },
        {
            "id": f"email-{lead_id}-2",
            "direction": "sent",
            "subject": f"Welcome {lead_name}",
            "from": "sales@autocrm.io",
            "to": lead_email,
            "sent_at": (now - timedelta(days=1, hours=2)).isoformat(),
            "snippet": "Sharing next steps and a short overview of the platform.",
        },
    ]


@router.get("/{lead_id}/calls")
async def get_lead_calls(
    lead_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Mock call timeline for a lead."""
    await _assert_can_view_lead(db, current_user, str(lead_id))
    now = datetime.now(timezone.utc)
    return [
        {
            "id": f"call-{lead_id}-1",
            "direction": "outbound",
            "duration_seconds": 420,
            "started_at": (now - timedelta(days=5, hours=1)).isoformat(),
            "outcome": "Connected",
            "note": "Discussed onboarding timeline and next steps.",
        },
        {
            "id": f"call-{lead_id}-2",
            "direction": "inbound",
            "duration_seconds": 180,
            "started_at": (now - timedelta(days=1, hours=6)).isoformat(),
            "outcome": "Left voicemail",
            "note": "Follow up needed on pricing questions.",
        },
    ]
