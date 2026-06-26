from __future__ import annotations

from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from supabase import Client

from app.auth.dependencies import require_admin, require_auth
from app.database import get_db, run_db_operation
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.organization import OrganizationCreate, OrganizationResponse, OrganizationUpdate
from app.utils.team_access import can_access_organization_record, can_assign_owned_record, get_agent_team_id

router = APIRouter()


def get_organization_repository(db: Client = Depends(get_db)) -> OrganizationRepository:
    return OrganizationRepository(db)


async def _assert_organization_access(db: Client, current_user: dict, organization: dict[str, Any]) -> None:
    if await can_access_organization_record(
        db,
        current_user,
        organization_id=str(organization.get("id") or ""),
        owner_id=str(organization.get("owner_id")) if organization.get("owner_id") else None,
        team_id=str(organization.get("team_id")) if organization.get("team_id") else None,
    ):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


async def _prepare_organization_ownership(
    db: Client,
    current_user: dict,
    payload: dict[str, Any],
    *,
    default_owner: bool,
) -> dict[str, Any]:
    owner_id = payload.get("owner_id")
    team_id = payload.get("team_id")

    if default_owner and owner_id is None and team_id is None:
        owner_id = current_user.get("id")
        payload["owner_id"] = str(owner_id) if owner_id else None

    if owner_id is not None:
        payload["owner_id"] = str(owner_id)
    if team_id is not None:
        payload["team_id"] = str(team_id)

    if not await can_assign_owned_record(
        db,
        current_user,
        owner_id=payload.get("owner_id"),
        team_id=payload.get("team_id"),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to assign organization")

    if payload.get("owner_id") and not payload.get("team_id"):
        payload["team_id"] = await get_agent_team_id(db, payload["owner_id"])

    return payload




def _workspace_scope_clause(current_user: dict, lead_alias: str = "l", owner_column: str | None = None) -> tuple[str, dict[str, Any]]:
    role = str(current_user.get("role") or "").strip().lower()
    user_id = str(current_user.get("id") or "")
    if role == "admin":
        return "", {}
    if role in {"manager", "sales_manager"}:
        owner_expr = owner_column or f"{lead_alias}.owner_id"
        return (
            f" AND EXISTS ("
            f"SELECT 1 FROM team_members tm "
            f"JOIN teams team_scope ON team_scope.id = tm.team_id "
            f"WHERE team_scope.manager_id = :scope_user_id AND tm.agent_id = {owner_expr}"
            f") ",
            {"scope_user_id": user_id},
        )
    owner_expr = owner_column or f"{lead_alias}.owner_id"
    return f" AND {owner_expr} = :scope_user_id ", {"scope_user_id": user_id}


async def _build_organization_workspace(db: Client, organization_id: str, current_user: dict) -> dict[str, Any]:
    def _query():
        with db.engine.connect() as conn:
            org = conn.execute(
                text("SELECT * FROM organizations WHERE id = :org_id"),
                {"org_id": organization_id},
            ).mappings().first()
            if not org:
                return None

            lead_scope, lead_scope_params = _workspace_scope_clause(current_user, "l")
            leads = conn.execute(
                text(
                    "SELECT l.* FROM leads l "
                    "WHERE l.organization_id = :org_id "
                    f"{lead_scope}"
                    "ORDER BY l.created_at DESC LIMIT 100"
                ),
                {"org_id": organization_id, **lead_scope_params},
            ).mappings().all()

            deal_scope, deal_scope_params = _workspace_scope_clause(current_user, "l", "d.owner_id")
            deals = conn.execute(
                text(
                    "SELECT d.*, l.name AS lead_name FROM deals d "
                    "LEFT JOIN leads l ON l.id = d.lead_id "
                    "WHERE d.organization_id = :org_id "
                    f"{deal_scope}"
                    "ORDER BY d.created_at DESC LIMIT 100"
                ),
                {"org_id": organization_id, **deal_scope_params},
            ).mappings().all()

            note_scope, note_scope_params = _workspace_scope_clause(current_user, "l")
            notes = conn.execute(
                text(
                    "SELECT n.*, l.name AS lead_name FROM notes n "
                    "LEFT JOIN leads l ON l.id = n.entity_id AND n.entity_type = 'lead' "
                    "WHERE ((n.entity_type = 'organization' AND n.entity_id = :org_id) "
                    "OR (n.entity_type = 'lead' AND l.organization_id = :org_id)) "
                    f"{note_scope}"
                    "ORDER BY n.created_at DESC LIMIT 100"
                ),
                {"org_id": organization_id, **note_scope_params},
            ).mappings().all()

            task_scope, task_scope_params = _workspace_scope_clause(current_user, "l")
            tasks = conn.execute(
                text(
                    "SELECT t.*, l.name AS lead_name FROM tasks t "
                    "LEFT JOIN leads l ON l.id = t.entity_id AND t.entity_type = 'lead' "
                    "WHERE ((t.entity_type = 'organization' AND t.entity_id = :org_id) "
                    "OR (t.entity_type = 'lead' AND l.organization_id = :org_id)) "
                    f"{task_scope}"
                    "ORDER BY t.due_at ASC NULLS LAST, t.created_at DESC LIMIT 100"
                ),
                {"org_id": organization_id, **task_scope_params},
            ).mappings().all()

            call_scope, call_scope_params = _workspace_scope_clause(current_user, "l")
            calls = conn.execute(
                text(
                    "SELECT c.*, l.name AS lead_name FROM call_sessions c "
                    "JOIN leads l ON l.id = c.lead_id "
                    "WHERE l.organization_id = :org_id "
                    f"{call_scope}"
                    "ORDER BY c.created_at DESC LIMIT 50"
                ),
                {"org_id": organization_id, **call_scope_params},
            ).mappings().all()

            open_statuses = {"new", "contacted", "nurture", "qualified", "proposal", "negotiation"}
            won_statuses = {"won", "closed_won"}
            lost_statuses = {"lost", "closed_lost"}
            deal_rows = [dict(row) for row in deals]
            open_deals = [deal for deal in deal_rows if str(deal.get("status") or deal.get("stage") or "").lower() in open_statuses]
            won_deals = [deal for deal in deal_rows if str(deal.get("status") or deal.get("stage") or "").lower() in won_statuses]
            lost_deals = [deal for deal in deal_rows if str(deal.get("status") or deal.get("stage") or "").lower() in lost_statuses]
            open_value = sum(float(deal.get("value") or 0) for deal in open_deals)
            won_value = sum(float(deal.get("value") or 0) for deal in won_deals)
            type_counts = {
                "new_business": 0,
                "upsell": 0,
                "renewal": 0,
                "cross_sell": 0,
            }
            for deal in deal_rows:
                deal_type = str(deal.get("deal_type") or "new_business").strip().lower()
                if deal_type not in type_counts:
                    deal_type = "new_business"
                type_counts[deal_type] += 1

            return {
                "organization": dict(org),
                "leads": [dict(row) for row in leads],
                "deals": deal_rows,
                "tasks": [dict(row) for row in tasks],
                "notes": [dict(row) for row in notes],
                "calls": [dict(row) for row in calls],
                "summary": {
                    "lead_count": len(leads),
                    "deal_count": len(deals),
                    "open_deal_count": len(open_deals),
                    "won_deal_count": len(won_deals),
                    "lost_deal_count": len(lost_deals),
                    "open_pipeline_value": open_value,
                    "won_revenue": won_value,
                    "task_count": len(tasks),
                    "note_count": len(notes),
                    "call_count": len(calls),
                    "deal_type_counts": type_counts,
                },
            }

    return await run_db_operation(_query)

@router.get("/", response_model=List[OrganizationResponse])
async def get_organizations(
    skip: int = 0,
    limit: int = 100,
    industry: str | None = None,
    search: str | None = None,
    current_user: dict = Depends(require_auth),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Get organizations with optional filtering."""
    return await repository.list_organizations_for_user(
        current_user=current_user,
        skip=skip,
        limit=limit,
        industry=industry,
        search=search,
    )



@router.get("/{organization_id}/workspace")
async def get_organization_workspace(
    organization_id: UUID,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Get organization/account workspace with linked CRM records."""
    organization = await repository.get_by_id(organization_id)
    await _assert_organization_access(db, current_user, organization)
    workspace = await _build_organization_workspace(db, str(organization_id), current_user)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return workspace


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Get an organization by ID."""
    organization = await repository.get_by_id(organization_id)
    await _assert_organization_access(db, current_user, organization)
    return organization


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Create a new organization."""
    organization_data = await _prepare_organization_ownership(
        db,
        current_user,
        payload.model_dump(),
        default_owner=True,
    )
    return await repository.create(organization_data)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdate,
    current_user: dict = Depends(require_auth),
    db: Client = Depends(get_db),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Update an organization."""
    existing = await repository.get_by_id(organization_id)
    await _assert_organization_access(db, current_user, existing)
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "owner_id" in update_data or "team_id" in update_data:
        update_data = await _prepare_organization_ownership(db, current_user, update_data, default_owner=False)

    return await repository.update_by_id(organization_id, update_data)


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: UUID,
    current_user: dict = Depends(require_admin()),
    repository: OrganizationRepository = Depends(get_organization_repository),
):
    """Delete an organization."""
    await repository.delete_by_id(organization_id)
    return None
