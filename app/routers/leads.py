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
from app.repositories.call_repository import CallRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.deal import DealResponse
from app.schemas.call import CallSessionResponse
from app.schemas.lead import LeadBulkAssignRequest, LeadConvertRequest, LeadCreate, LeadResponse, LeadUpdate
from app.services.conversion_service import ConversionService
from app.services.import_service import ImportService
from app.services.notification_service import NotificationService
from app.services.email_service import MailjetEmailService
from app.services.status_change_log_service import StatusChangeLogService
from app.services.lead_scoring_service import calculate_lead_score
from app.utils.statuses import LEAD_STATUSES, normalize_status
from app.utils.team_access import can_access_lead, is_manager_of_rep

router = APIRouter()


def get_lead_repository(db: Client = Depends(get_db)) -> LeadRepository:
    return LeadRepository(db)


def get_deal_repository(db: Client = Depends(get_db)) -> DealRepository:
    return DealRepository(db)


def get_call_repository(db: Client = Depends(get_db)) -> CallRepository:
    return CallRepository(db)


def get_import_service(db: Client = Depends(get_db)) -> ImportService:
    return ImportService(db)


def get_conversion_service(db: Client = Depends(get_db)) -> ConversionService:
    return ConversionService(db)


def get_notification_service(db: Client = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


def get_email_service(db: Client = Depends(get_db)) -> MailjetEmailService:
    return MailjetEmailService(db)


def get_status_log_service(db: Client = Depends(get_db)) -> StatusChangeLogService:
    return StatusChangeLogService(db)


def _can_manage_leads(current_user: dict) -> bool:
    role = str(current_user.get("role") or "").strip().lower()
    return role == "admin"


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
    if await can_access_lead(db, current_user, lead_id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


async def _can_manager_assign_to_rep(db: Client, manager_id: str, rep_id: str) -> bool:
    return await is_manager_of_rep(db, manager_id, rep_id)


async def _get_agent_role(db: Client, agent_id: str) -> str | None:
    def _query():
        engine = getattr(db, "engine", None)
        if engine is not None:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT role FROM agents WHERE id = :agent_id"),
                    {"agent_id": agent_id},
                ).mappings().first()
                return str(row.get("role")) if row and row.get("role") else None

        rows = db.table("agents").select("*").eq("id", agent_id).limit(1).execute().data or []
        row = rows[0] if rows else None
        return str(row.get("role")) if row and row.get("role") else None

    return await run_db_operation(_query)


async def _is_admin_assignable_manager(db: Client, agent_id: str) -> bool:
    role = str(await _get_agent_role(db, agent_id) or "").strip().lower()
    return role in {"manager", "sales_manager"}




async def _find_or_create_organization_for_company(
    db: Client,
    company: str | None,
    *,
    owner_id: str | None = None,
) -> str | None:
    company_name = (company or "").strip()
    if not company_name:
        return None

    def _query():
        with db.engine.begin() as conn:
            existing = conn.execute(
                text("SELECT id FROM organizations WHERE lower(name) = lower(:name) LIMIT 1"),
                {"name": company_name},
            ).mappings().first()
            if existing:
                return str(existing["id"])
            team_id = get_agent_team_id_sync(conn, owner_id) if owner_id else None
            created = conn.execute(
                text(
                    "INSERT INTO organizations (name, owner_id, team_id) VALUES (:name, :owner_id, :team_id) "
                    "RETURNING id"
                ),
                {"name": company_name, "owner_id": owner_id, "team_id": team_id},
            ).mappings().first()
            return str(created["id"]) if created else None

    return await run_db_operation(_query)


def get_agent_team_id_sync(conn, agent_id: str | None) -> str | None:
    if not agent_id:
        return None
    row = conn.execute(
        text(
            "SELECT COALESCE(a.team_id, tm.team_id) AS team_id "
            "FROM agents a "
            "LEFT JOIN team_members tm ON tm.agent_id = a.id "
            "WHERE a.id = :agent_id LIMIT 1"
        ),
        {"agent_id": agent_id},
    ).mappings().first()
    return str(row.get("team_id")) if row and row.get("team_id") else None


async def _get_lead_ai_history(db: Client, lead_id: str) -> list[dict[str, Any]]:
    def _query():
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT aa.id, aa.action_type, aa.reason, aa.approval_status, aa.dispatch_status, "
                    "aa.crm_record_type, aa.crm_record_id, aa.created_at, ar.trigger_type, ar.status AS run_status "
                    "FROM ai_agent_actions aa LEFT JOIN ai_agent_runs ar ON ar.id = aa.run_id "
                    "WHERE aa.entity_type='lead' AND aa.entity_id=:lead_id "
                    "ORDER BY aa.created_at DESC LIMIT 50"
                ),
                {"lead_id": lead_id},
            ).mappings().all()
            return [dict(row) for row in rows]
    return await run_db_operation(_query)


def _build_mock_lead_emails(lead_id: str, lead_name: str | None, lead_email: str | None) -> list[dict[str, Any]]:
    display_name = lead_name or "Lead"
    display_email = lead_email or "unknown@example.com"
    now = datetime.now(timezone.utc)
    return [
        {
            "id": f"email-{lead_id}-1",
            "direction": "received",
            "subject": f"Re: {display_name} onboarding",
            "from": display_email,
            "to": "sales@autocrm.io",
            "sent_at": (now - timedelta(days=2, hours=3)).isoformat(),
            "snippet": "Thanks for the details, can we schedule a quick call?",
        },
        {
            "id": f"email-{lead_id}-2",
            "direction": "sent",
            "subject": f"Welcome {display_name}",
            "from": "sales@autocrm.io",
            "to": display_email,
            "sent_at": (now - timedelta(days=1, hours=2)).isoformat(),
            "snippet": "Sharing next steps and a short overview of the platform.",
        },
    ]


async def _get_lead_workspace(db: Client, lead_id: str) -> dict[str, Any]:
    def _query():
        with db.engine.connect() as conn:
            lead = conn.execute(
                text("SELECT * FROM leads WHERE id = :lead_id"),
                {"lead_id": lead_id},
            ).mappings().first()
            if not lead:
                return None

            owner = conn.execute(
                text(
                    "SELECT a.full_name, a.email "
                    "FROM leads l "
                    "LEFT JOIN agents a ON a.id = l.owner_id "
                    "WHERE l.id = :lead_id"
                ),
                {"lead_id": lead_id},
            ).mappings().first()

            calls = conn.execute(
                text(
                    "SELECT * FROM call_sessions "
                    "WHERE lead_id = :lead_id "
                    "ORDER BY started_at DESC LIMIT 50"
                ),
                {"lead_id": lead_id},
            ).mappings().all()

            tasks = conn.execute(
                text(
                    "SELECT t.*, l.name AS lead_name, a.full_name AS assignee_name, a.email AS assignee_email "
                    "FROM tasks t "
                    "LEFT JOIN leads l ON l.id = t.entity_id AND t.entity_type = 'lead' "
                    "LEFT JOIN agents a ON a.id = t.assigned_to "
                    "WHERE t.entity_type = 'lead' AND t.entity_id = :lead_id "
                    "ORDER BY t.due_at ASC NULLS LAST, t.created_at DESC LIMIT 50"
                ),
                {"lead_id": lead_id},
            ).mappings().all()

            notes = conn.execute(
                text(
                    "SELECT * FROM notes "
                    "WHERE entity_type = 'lead' AND entity_id = :lead_id "
                    "ORDER BY created_at DESC LIMIT 50"
                ),
                {"lead_id": lead_id},
            ).mappings().all()

            ai_history = conn.execute(
                text(
                    "SELECT aa.id, aa.action_type, aa.reason, aa.approval_status, aa.dispatch_status, "
                    "aa.crm_record_type, aa.crm_record_id, aa.created_at, ar.trigger_type, ar.status AS run_status "
                    "FROM ai_agent_actions aa LEFT JOIN ai_agent_runs ar ON ar.id = aa.run_id "
                    "WHERE aa.entity_type='lead' AND aa.entity_id=:lead_id "
                    "ORDER BY aa.created_at DESC LIMIT 50"
                ),
                {"lead_id": lead_id},
            ).mappings().all()

            lead_dict = dict(lead)
            owner_dict = dict(owner) if owner else {}
            return {
                "lead": lead_dict,
                "owner": {
                    "name": str(owner_dict.get("full_name")) if owner_dict.get("full_name") else None,
                    "email": str(owner_dict.get("email")) if owner_dict.get("email") else None,
                },
                "emails": _build_mock_lead_emails(
                    lead_id,
                    str(lead_dict.get("name")) if lead_dict.get("name") else None,
                    str(lead_dict.get("email")) if lead_dict.get("email") else None,
                ),
                "calls": [dict(row) for row in calls],
                "tasks": [dict(row) for row in tasks],
                "notes": [dict(row) for row in notes],
                "ai_history": [dict(row) for row in ai_history],
            }

    workspace = await run_db_operation(_query)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return workspace


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
        if await _is_admin_assignable_manager(db, owner_id):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins can assign leads only to managers")
    if role in {"sales_manager", "manager"} and owner_id == user_id:
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
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Get leads with optional filtering."""
    role = str(current_user.get("role") or "").strip().lower()
    requester_id = str(current_user.get("id") or "")
    if not requester_id:
        return []

    if role in {"manager", "sales_manager"}:
        if owner_id is not None:
            requested_owner_id = str(owner_id)
            if requested_owner_id != requester_id and not await _can_manager_assign_to_rep(db, requester_id, requested_owner_id):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        def _query_team_leads():
            engine = getattr(db, "engine", None)
            if engine is not None:
                with engine.connect() as conn:
                    sql = (
                        "SELECT DISTINCT l.* FROM leads l "
                        "LEFT JOIN team_members tm ON tm.agent_id = l.owner_id "
                        "LEFT JOIN teams t ON t.id = tm.team_id "
                        "WHERE (l.owner_id = :mid OR t.manager_id = :mid) "
                    )
                    params: dict[str, Any] = {"mid": requester_id}
                    if owner_id:
                        sql += "AND l.owner_id = :owner_id "
                        params["owner_id"] = str(owner_id)
                    if status:
                        sql += "AND l.status = :status "
                        params["status"] = status
                    if organization_id:
                        sql += "AND l.organization_id = :org_id "
                        params["org_id"] = str(organization_id)
                    if source:
                        sql += "AND l.source = :source "
                        params["source"] = source
                    if search:
                        sql += "AND l.name ILIKE :search "
                        params["search"] = f"%{search}%"
                    sql += "ORDER BY l.created_at DESC OFFSET :skip LIMIT :limit"
                    params["skip"] = skip
                    params["limit"] = limit
                    rows = conn.execute(text(sql), params).mappings().all()
                    return [dict(row) for row in rows]

            tables = getattr(db, "tables", {})
            team_ids = {str(team.get("id")) for team in tables.get("teams", []) if str(team.get("manager_id")) == requester_id}
            member_ids = {
                str(member.get("agent_id"))
                for member in tables.get("team_members", [])
                if str(member.get("team_id")) in team_ids
            }
            visible_owner_ids = {requester_id, *member_ids}
            rows = [
                lead.copy()
                for lead in tables.get("leads", [])
                if str(lead.get("owner_id") or "") in visible_owner_ids
            ]
            if owner_id:
                rows = [lead for lead in rows if str(lead.get("owner_id") or "") == str(owner_id)]
            if status:
                rows = [lead for lead in rows if str(lead.get("status") or "") == status]
            if organization_id:
                rows = [lead for lead in rows if str(lead.get("organization_id") or "") == str(organization_id)]
            if source:
                rows = [lead for lead in rows if str(lead.get("source") or "") == source]
            if search:
                rows = [lead for lead in rows if search.lower() in str(lead.get("name") or "").lower()]
            return rows[skip : skip + limit]

        return await run_db_operation(_query_team_leads)

    if not _can_manage_leads(current_user):
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


@router.get("/assignment-reps")
async def get_assignment_reps(
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """List users available for lead assignment in the current actor's scope."""
    role = str(current_user.get("role") or "").strip().lower()
    if role not in {"admin", "manager", "sales_manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    def _query():
        engine = getattr(db, "engine", None)
        if engine is not None:
            with engine.connect() as conn:
                if str(current_user.get("role") or "").strip().lower() == "admin":
                    rows = conn.execute(
                        text(
                            "SELECT id, full_name, email, role FROM agents "
                            "WHERE role IN ('manager', 'sales_manager') "
                            "ORDER BY created_at DESC"
                        )
                    ).mappings().all()
                    return [dict(row) for row in rows]

                rows = conn.execute(
                    text(
                        "SELECT a.id, a.full_name, a.email, a.role "
                        "FROM team_members tm "
                        "JOIN teams t ON t.id = tm.team_id "
                        "JOIN agents a ON a.id = tm.agent_id "
                        "WHERE t.manager_id = :mid "
                        "ORDER BY a.created_at DESC"
                    ),
                    {"mid": str(current_user.get("id"))},
                ).mappings().all()
                return [dict(row) for row in rows]

        tables = getattr(db, "tables", {})
        if role == "admin":
            return [
                {
                    "id": agent.get("id"),
                    "full_name": agent.get("full_name"),
                    "email": agent.get("email"),
                    "role": agent.get("role"),
                }
                for agent in tables.get("agents", [])
                if str(agent.get("role") or "").strip().lower() in {"manager", "sales_manager"}
            ]

        team_ids = {str(team.get("id")) for team in tables.get("teams", []) if str(team.get("manager_id")) == str(current_user.get("id"))}
        member_ids = {
            str(member.get("agent_id"))
            for member in tables.get("team_members", [])
            if str(member.get("team_id")) in team_ids
        }
        return [
            {
                "id": agent.get("id"),
                "full_name": agent.get("full_name"),
                "email": agent.get("email"),
                "role": agent.get("role"),
            }
            for agent in tables.get("agents", [])
            if str(agent.get("id")) in member_ids
        ]

    return await run_db_operation(_query)




@router.post("/{lead_id}/score/recalculate")
async def recalculate_lead_score(
    lead_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    await _assert_can_view_lead(db, current_user, str(lead_id))
    result = await calculate_lead_score(db, str(lead_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return result


@router.get("/{lead_id}/ai-history")
async def get_lead_ai_history(
    lead_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    await _assert_can_view_lead(db, current_user, str(lead_id))
    return await _get_lead_ai_history(db, str(lead_id))


@router.get("/{lead_id}/workspace")
async def get_lead_workspace(
    lead_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    await _assert_can_view_lead(db, current_user, str(lead_id))
    await calculate_lead_score(db, str(lead_id))
    return await _get_lead_workspace(db, str(lead_id))


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: UUID,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Get a lead by ID."""
    await _assert_can_view_lead(db, current_user, str(lead_id))
    return await repository.get_by_id(lead_id)


@router.post("/", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
    notification_service: NotificationService = Depends(get_notification_service),
    email_service: MailjetEmailService = Depends(get_email_service),
    status_log_service: StatusChangeLogService = Depends(get_status_log_service),
):
    """Create a new lead."""
    lead_data = payload.model_dump()

    try:
        lead_data["status"] = normalize_status(lead_data.get("status") or "new", LEAD_STATUSES)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    actor_role = str(current_user.get("role") or "").strip().lower()
    owner_id = lead_data.get("owner_id")
    if not owner_id and actor_role != "admin":
        owner_id = current_user.get("id")
    if owner_id:
        lead_data["owner_id"] = str(owner_id)
        await _assert_lead_assignment_permissions(db, current_user, lead_data["owner_id"])

    organization_id = lead_data.get("organization_id")
    if organization_id:
        lead_data["organization_id"] = str(organization_id)
    elif lead_data.get("company"):
        lead_data["organization_id"] = await _find_or_create_organization_for_company(
            db,
            lead_data.get("company"),
            owner_id=lead_data.get("owner_id"),
        )

    created = await repository.create(lead_data)
    score_result = await calculate_lead_score(db, str(created.get("id")))
    if score_result:
        created = {**created, **score_result}
    await status_log_service.log_change(
        entity_type="lead",
        entity_id=str(created.get("id")),
        old_status=None,
        new_status=created.get("status") or "new",
        changed_by=str(current_user.get("id") or "") or None,
    )
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
        try:
            recipient_id = str(created.get("owner_id"))
            recipient_email = await email_service.get_recipient_email(recipient_id)
            if recipient_email:
                await email_service.send_lead_assigned_email(
                    recipient_id=recipient_id,
                    recipient_email=recipient_email,
                    actor_name=actor_name or "Manager",
                    lead_name=created.get("name") or "Untitled Lead",
                )
        except Exception:
            pass
    return created


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
    notification_service: NotificationService = Depends(get_notification_service),
    email_service: MailjetEmailService = Depends(get_email_service),
    status_log_service: StatusChangeLogService = Depends(get_status_log_service),
):
    """Update a lead."""
    existing = await repository.get_by_id(lead_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] is not None:
        try:
            update_data["status"] = normalize_status(update_data["status"], LEAD_STATUSES)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    await _assert_can_view_lead(db, current_user, str(lead_id))

    if "owner_id" in update_data and update_data["owner_id"] is not None:
        update_data["owner_id"] = str(update_data["owner_id"])
        await _assert_lead_assignment_permissions(db, current_user, update_data["owner_id"])

    if "organization_id" in update_data and update_data["organization_id"] is not None:
        update_data["organization_id"] = str(update_data["organization_id"])

    updated = await repository.update_by_id(lead_id, update_data)
    score_result = await calculate_lead_score(db, str(lead_id))
    if score_result:
        updated = {**updated, **score_result}
    old_status = existing.get("status")
    new_status = updated.get("status")
    if new_status and new_status != old_status:
        await status_log_service.log_change(
            entity_type="lead",
            entity_id=str(updated.get("id")),
            old_status=old_status,
            new_status=new_status,
            changed_by=str(current_user.get("id") or "") or None,
        )
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
        try:
            recipient_email = await email_service.get_recipient_email(next_owner_id)
            if recipient_email:
                await email_service.send_lead_assigned_email(
                    recipient_id=next_owner_id,
                    recipient_email=recipient_email,
                    actor_name=actor_name or "Manager",
                    lead_name=updated.get("name") or "Untitled Lead",
                )
        except Exception:
            pass
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


@router.post("/assign-bulk", response_model=List[LeadResponse])
async def bulk_assign_leads(
    payload: LeadBulkAssignRequest,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: LeadRepository = Depends(get_lead_repository),
):
    """Assign multiple leads in one request."""
    updated_rows: list[dict[str, Any]] = []
    for item in payload.assignments:
        owner_id = str(item.owner_id) if item.owner_id else None
        await _assert_can_view_lead(db, current_user, str(item.lead_id))
        await _assert_lead_assignment_permissions(db, current_user, owner_id)
        updated = await repository.update_by_id(str(item.lead_id), {"owner_id": owner_id})
        updated_rows.append(updated)
    return updated_rows


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
            stage=payload.stage or "qualification",
            value=payload.value,
            currency=payload.currency or "USD",
            expected_close_at=payload.expected_close_at,
            owner_id=str(payload.owner_id) if payload.owner_id else None,
            organization_id=str(payload.organization_id) if payload.organization_id else None,
            actor_id=str(current_user.get("id") or "") or None,
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
    """Mark the latest deal for a lead as unqualified (manager/admin only)."""
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
        return await service.update_deal_status(
            deal_id=deal_id,
            new_status="qualification",
            actor_id=str(current_user.get("id") or "") or None,
        )
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
    actor_role = str(current_user.get("role") or "").strip().lower()
    return await service.ingest_lead_payload(
        payload=payload,
        owner_id=None if actor_role == "admin" else str(current_user.get("id") or "") or None,
    )


@router.get("/{lead_id}/emails")
async def get_lead_emails(
    lead_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Mock email timeline for a lead."""
    await _assert_can_view_lead(db, current_user, str(lead_id))
    profile = await _get_lead_profile(db, str(lead_id))
    return _build_mock_lead_emails(str(lead_id), profile.get("name"), profile.get("email"))


@router.get("/{lead_id}/calls", response_model=List[CallSessionResponse])
async def get_lead_calls(
    lead_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: CallRepository = Depends(get_call_repository),
):
    """Call timeline for a lead."""
    await _assert_can_view_lead(db, current_user, str(lead_id))
    return await repository.list_calls_by_lead(lead_id=str(lead_id), skip=0, limit=50)
