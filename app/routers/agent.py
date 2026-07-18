from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import text
from supabase import Client

from app.auth.dependencies import (
    require_auth,
    require_admin,
    require_ai_agent_auth,
    require_human_or_ai_agent_auth,
    require_sales_manager_or_admin,
    generate_ai_service_token,
)
from app.database import get_db, run_db_operation
from app.repositories.agent_control_repository import (
    AgentActionRepository,
    AgentApprovalRepository,
    AgentRunRepository,
    AgentSettingRepository,
    AgentTraceRepository,
    AiAgentCredentialRepository,
    AiAgentRepository,
)
from app.repositories.note_repository import NoteRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.agent_action import (
    AgentActionIn,
    AgentActionResponse,
    AgentApprovalDecision,
    AgentRunCreate,
    AgentRunResponse,
    AgentRunUpdate,
    AgentSettingResponse,
    AgentSettingUpdate,
    AgentTraceCreate,
    AiAgentCredentialCreate,
    AiAgentUpdate,
)
from app.schemas.task_deadline import (
    TaskDeadlineAlertIn,
    TaskDeadlineAlertResponse,
    TaskDeadlineCandidateList,
)
from app.schemas.note import NoteCreate
from app.schemas.task import TaskCreate
from app.services.lead_scoring_service import queue_lead_score_sweep
from app.services.notification_service import NotificationService
from app.services.task_deadline_service import TaskDeadlineService

router = APIRouter()

RISKY_ACTIONS = {"create_task", "send_email", "update_deal_stage", "update_lead_status"}
SUPPORTED_ACTIONS = {"create_task", "create_note", "create_alert"}

AI_AGENT_RUNTIME_ALIASES = {
    "action_manager_agent": {"action_manager_agent", "action_manager", "task_auto", "create_task"},
    "lead_assistant": {"lead_assistant", "stale_lead", "lead_nudge"},
    "deal_risk_watcher": {"deal_risk_watcher", "deal_risk"},
    "daily_summary_assistant": {"daily_summary_assistant", "daily_summary", "summary_assistant"},
    "meeting_agent": {"meeting_agent", "meeting_assistant", "meeting_complete", "meeting_intel"},
    "task_deadline_watcher": {"task_deadline_watcher", "task_deadline_watch", "deadline_watch"},
}
IMPLEMENTED_AI_AGENT_KEYS = set(AI_AGENT_RUNTIME_ALIASES.keys())

DEFAULT_AI_AGENT_REGISTRY = [
    {
        "agent_key": "action_manager_agent",
        "display_name": "Action Manager Agent",
        "description": "Creates and dispatches playbook task actions.",
        "agent_type": "action_manager",
    },
    {
        "agent_key": "lead_assistant",
        "display_name": "Lead Assistant",
        "description": "Monitors lead health and suggests follow-ups.",
        "agent_type": "lead_assistant",
    },
    {
        "agent_key": "deal_risk_watcher",
        "display_name": "Deal Risk Watcher",
        "description": "Detects at-risk deals and triggers alerts.",
        "agent_type": "deal_risk_watcher",
    },
    {
        "agent_key": "daily_summary_assistant",
        "display_name": "Daily Summary Assistant",
        "description": "Produces daily CRM performance digests.",
        "agent_type": "summary_assistant",
    },
    {
        "agent_key": "meeting_agent",
        "display_name": "Meeting Agent",
        "description": "Summarizes completed meetings and creates actions.",
        "agent_type": "meeting_assistant",
    },
    {
        "agent_key": "task_deadline_watcher",
        "display_name": "Task Deadline Watcher",
        "description": "Monitors due and overdue tasks, escalates risk, and drafts internal recovery guidance.",
        "agent_type": "task_deadline_watcher",
    },
]


def get_task_repository(db: Client = Depends(get_db)) -> TaskRepository:
    return TaskRepository(db)


def get_note_repository(db: Client = Depends(get_db)) -> NoteRepository:
    return NoteRepository(db)


def get_notification_service(db: Client = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


def get_task_deadline_service(db: Client = Depends(get_db)) -> TaskDeadlineService:
    return TaskDeadlineService(db)


def get_run_repository(db: Client = Depends(get_db)) -> AgentRunRepository:
    return AgentRunRepository(db)


def get_trace_repository(db: Client = Depends(get_db)) -> AgentTraceRepository:
    return AgentTraceRepository(db)


def get_action_repository(db: Client = Depends(get_db)) -> AgentActionRepository:
    return AgentActionRepository(db)


def get_approval_repository(db: Client = Depends(get_db)) -> AgentApprovalRepository:
    return AgentApprovalRepository(db)


def get_setting_repository(db: Client = Depends(get_db)) -> AgentSettingRepository:
    return AgentSettingRepository(db)


def get_ai_agent_repository(db=Depends(get_db)) -> AiAgentRepository:
    return AiAgentRepository(db)


def get_ai_agent_credential_repository(db=Depends(get_db)) -> AiAgentCredentialRepository:
    return AiAgentCredentialRepository(db)


async def _enrich_approvals_with_actions(
    approvals: list[dict[str, Any]],
    action_repository: AgentActionRepository,
    db: Client | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for approval in approvals:
        row = dict(approval)
        try:
            action = await action_repository.get_by_id(row.get("action_id"))
        except Exception:
            action = None
        if action:
            row["action_type"] = action.get("action_type")
            row["entity_type"] = action.get("entity_type")
            row["entity_id"] = action.get("entity_id")
            row["payload"] = action.get("payload")
            row["action_reason"] = action.get("reason")
        enriched.append(row)
    if db is not None:
        return await _enrich_control_rows(db, enriched)
    return enriched


async def _load_control_center_snapshot_fast(
    db: Client,
    *,
    runs_limit: int,
    source_window: int,
) -> dict[str, list[dict[str, Any]]] | None:
    if not hasattr(db, "engine"):
        return None

    def _query() -> dict[str, list[dict[str, Any]]]:
        with db.engine.connect() as conn:
            runs = [
                dict(row)
                for row in conn.execute(
                    text(
                        """
                        SELECT id, external_run_id, trigger_type, entity_id, entity_type,
                               status, event_payload, context_payload, plan_payload, summary,
                               failure_cause, failure_detail, started_at, finished_at
                        FROM ai_agent_runs
                        ORDER BY started_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"limit": source_window},
                ).mappings().all()
            ]
            agent_runs = [
                dict(row)
                for row in conn.execute(
                    text(
                        """
                        SELECT id, external_run_id, trigger_type, entity_id, entity_type,
                               status, summary, started_at, finished_at
                        FROM ai_agent_runs
                        ORDER BY started_at DESC
                        LIMIT 5000
                        """
                    )
                ).mappings().all()
            ]
            approvals = [
                dict(row)
                for row in conn.execute(
                    text(
                        """
                        SELECT apr.id, apr.action_id, apr.state, apr.requested_by, apr.approver_id,
                               apr.reason, apr.approver_note, apr.created_at, apr.decided_at,
                               aa.action_type, aa.entity_type, aa.entity_id, aa.payload,
                               aa.reason AS action_reason
                        FROM ai_agent_approval_requests apr
                        LEFT JOIN ai_agent_actions aa ON aa.id = apr.action_id
                        WHERE apr.state = 'pending'
                        ORDER BY apr.created_at ASC
                        LIMIT 100
                        """
                    )
                ).mappings().all()
            ]
            agents = [
                dict(row)
                for row in conn.execute(
                    text(
                        """
                        SELECT id, agent_key, display_name, description, agent_type, status,
                               enabled, capabilities, config, service_url, last_seen_at,
                               created_at, updated_at
                        FROM ai_agents
                        ORDER BY display_name ASC
                        LIMIT 100
                        """
                    )
                ).mappings().all()
            ]
            actions = [
                dict(row)
                for row in conn.execute(
                    text(
                        """
                        SELECT id, run_id, external_run_id, action_type, entity_type, entity_id,
                               reason, payload, idempotency_key, approval_status,
                               dispatch_status, created_by, crm_record_type, crm_record_id,
                               created_at, executed_at
                        FROM ai_agent_actions
                        ORDER BY created_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"limit": max(1000, runs_limit * 40)},
                ).mappings().all()
            ]
            metrics = dict(
                conn.execute(
                    text(
                        """
                        SELECT
                            COUNT(*) FILTER (WHERE lower(COALESCE(status, '')) IN ('running', 'pending')) AS running,
                            COUNT(*) FILTER (WHERE lower(COALESCE(status, '')) LIKE '%fail%') AS failed,
                            COUNT(*) FILTER (WHERE lower(COALESCE(status, '')) LIKE '%complete%') AS completed,
                            COUNT(*) AS total_runs
                        FROM ai_agent_runs
                        """
                    )
                ).mappings().first()
                or {}
            )
            metrics["pending_approvals"] = len(approvals)
        return {
            "runs": runs,
            "agent_runs": agent_runs,
            "approvals": approvals,
            "agents": agents,
            "actions": actions,
            "metrics": metrics,
        }

    try:
        return await run_db_operation(_query)
    except Exception:
        return None


async def _load_pending_approvals_fast(db: Client, *, limit: int = 100) -> list[dict[str, Any]] | None:
    if not hasattr(db, "engine"):
        return None

    def _query() -> list[dict[str, Any]]:
        with db.engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    text(
                        """
                        SELECT apr.id, apr.action_id, apr.state, apr.requested_by, apr.approver_id,
                               apr.reason, apr.approver_note, apr.created_at, apr.decided_at,
                               aa.action_type, aa.entity_type, aa.entity_id, aa.payload,
                               aa.reason AS action_reason
                        FROM ai_agent_approval_requests apr
                        LEFT JOIN ai_agent_actions aa ON aa.id = apr.action_id
                        WHERE apr.state = 'pending'
                        ORDER BY apr.created_at ASC
                        LIMIT :limit
                        """
                    ),
                    {"limit": limit},
                ).mappings().all()
            ]

    try:
        return await run_db_operation(_query)
    except Exception:
        return None


def _build_control_center_metrics(
    runs: list[dict[str, Any]],
    approvals: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "running": sum(1 for run in runs if str(run.get("status") or "").lower() in {"running", "pending"}),
        "failed": sum(1 for run in runs if "fail" in str(run.get("status") or "").lower()),
        "completed": sum(1 for run in runs if "complete" in str(run.get("status") or "").lower()),
        "pending_approvals": len(approvals),
        "total_runs": len(runs),
    }


def _normalize_entity_type(value: object) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {"org": "organization", "organisation": "organization", "agent": "user", "rep": "user"}
    return aliases.get(normalized, normalized)


def _entity_label(entity_type: object) -> str:
    labels = {
        "lead": "Lead",
        "deal": "Deal",
        "organization": "Organization",
        "customer": "Customer",
        "user": "User",
        "task": "Task",
        "note": "Note",
        "call": "Call",
        "call_session": "Call",
        "ticket": "Ticket",
        "ai_interaction": "AI interaction",
    }
    normalized = _normalize_entity_type(entity_type)
    return labels.get(normalized, str(entity_type or "Record").replace("_", " ").title())


def _collect_entity_refs(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    payload_id_keys = {
        "lead_id": "lead",
        "deal_id": "deal",
        "organization_id": "organization",
        "org_id": "organization",
        "customer_id": "customer",
        "recipient_id": "user",
        "assigned_to": "user",
        "owner_id": "user",
        "created_by": "user",
        "actor_id": "user",
    }
    for row in rows:
        entity_type = _normalize_entity_type(row.get("entity_type"))
        entity_id = str(row.get("entity_id") or "").strip()
        if entity_type and entity_id:
            refs.add((entity_type, entity_id))
        for key in ("requested_by", "approver_id", "created_by"):
            value = str(row.get(key) or "").strip()
            if value:
                refs.add(("user", value))
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        for key, ref_type in payload_id_keys.items():
            value = str(payload.get(key) or "").strip()
            if value:
                refs.add((ref_type, value))
    return refs


async def _load_entity_names(db: Client, refs: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    if not refs or not hasattr(db, "engine"):
        return {}
    ids_by_type: dict[str, list[str]] = {}
    for entity_type, entity_id in refs:
        ids_by_type.setdefault(entity_type, []).append(entity_id)

    def _query_names() -> dict[tuple[str, str], str]:
        names: dict[tuple[str, str], str] = {}
        queries = {
            "lead": "SELECT id::text AS id, COALESCE(NULLIF(name, ''), NULLIF(email, ''), 'Lead') AS name FROM leads WHERE id::text = ANY(:ids)",
            "organization": "SELECT id::text AS id, COALESCE(NULLIF(name, ''), 'Organization') AS name FROM organizations WHERE id::text = ANY(:ids)",
            "deal": """
                SELECT d.id::text AS id,
                       COALESCE(NULLIF(o.name, ''), NULLIF(l.company, ''), NULLIF(l.name, ''), 'Deal') AS name
                FROM deals d
                LEFT JOIN organizations o ON o.id = d.organization_id
                LEFT JOIN leads l ON l.id = d.lead_id
                WHERE d.id::text = ANY(:ids)
            """,
            "user": "SELECT id::text AS id, COALESCE(NULLIF(full_name, ''), NULLIF(email, ''), 'User') AS name FROM agents WHERE id::text = ANY(:ids)",
            "customer": "SELECT id::text AS id, COALESCE(NULLIF(full_name, ''), NULLIF(company, ''), NULLIF(email, ''), 'Customer') AS name FROM customers WHERE id::text = ANY(:ids)",
            "task": "SELECT id::text AS id, COALESCE(NULLIF(title, ''), 'Task') AS name FROM tasks WHERE id::text = ANY(:ids)",
            "note": "SELECT id::text AS id, COALESCE(NULLIF(title, ''), LEFT(NULLIF(content, ''), 60), 'Note') AS name FROM notes WHERE id::text = ANY(:ids)",
            "call": """
                SELECT c.id::text AS id, COALESCE(NULLIF(l.name, ''), 'Call') AS name
                FROM call_sessions c
                LEFT JOIN leads l ON l.id = c.lead_id
                WHERE c.id::text = ANY(:ids)
            """,
            "call_session": """
                SELECT c.id::text AS id, COALESCE(NULLIF(l.name, ''), 'Call') AS name
                FROM call_sessions c
                LEFT JOIN leads l ON l.id = c.lead_id
                WHERE c.id::text = ANY(:ids)
            """,
        }
        with db.engine.connect() as conn:
            for entity_type, ids in ids_by_type.items():
                query = queries.get(entity_type)
                if not query or not ids:
                    continue
                for row in conn.execute(text(query), {"ids": ids}).mappings().all():
                    names[(entity_type, str(row["id"]))] = str(row.get("name") or _entity_label(entity_type))
        return names

    try:
        return await run_db_operation(_query_names)
    except Exception:
        return {}


def _action_display_title(action_type: object) -> str:
    labels = {
        "create_task": "Create follow-up task",
        "create_note": "Create note",
        "create_alert": "Create risk alert",
        "send_email": "Send email",
        "update_deal_stage": "Update deal stage",
        "update_lead_status": "Update lead status",
        "deal_risk": "Deal risk analysis",
        "lead_nudge": "Lead follow-up recommendation",
        "daily_summary": "Daily summary",
        "agent_action_callback": "AI action callback",
    }
    normalized = str(action_type or "").strip().lower()
    return labels.get(normalized, normalized.replace("_", " ").title() or "AI action")


def _payload_summary(payload: object, fallback: object = None) -> str:
    data = payload if isinstance(payload, dict) else {}
    for key in ("title", "message", "summary", "description", "content"):
        value = str(data.get(key) or "").strip()
        if value:
            return _truncate(value, 220)
    return _truncate(fallback or "No summary provided.", 220)


async def _enrich_control_rows(db: Client, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entity_names = await _load_entity_names(db, _collect_entity_refs(rows))
    payload_id_keys = {
        "lead_id": "lead",
        "deal_id": "deal",
        "organization_id": "organization",
        "org_id": "organization",
        "customer_id": "customer",
        "recipient_id": "user",
        "assigned_to": "user",
        "owner_id": "user",
        "created_by": "user",
        "actor_id": "user",
    }
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        entity_type = _normalize_entity_type(item.get("entity_type"))
        entity_id = str(item.get("entity_id") or "").strip()
        entity_name = entity_names.get((entity_type, entity_id)) if entity_type and entity_id else None
        item["entity_type"] = entity_type or item.get("entity_type")
        item["entity_display_type"] = _entity_label(entity_type)
        item["entity_display_name"] = entity_name
        item["entity_display_label"] = f"{_entity_label(entity_type)}: {entity_name}" if entity_name else _entity_label(entity_type)

        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        related_entities = []
        for key, ref_type in payload_id_keys.items():
            ref_id = str(payload.get(key) or "").strip()
            if not ref_id:
                continue
            related_entities.append({
                "field": key,
                "type": ref_type,
                "label": _entity_label(ref_type),
                "name": entity_names.get((ref_type, ref_id)),
            })
        item["related_entities"] = related_entities
        item["action_display_title"] = _action_display_title(item.get("action_type") or item.get("trigger_type"))
        item["action_summary"] = _payload_summary(payload, item.get("action_reason") or item.get("reason") or item.get("summary"))

        for user_field in ("requested_by", "approver_id", "created_by"):
            user_id = str(item.get(user_field) or "").strip()
            if user_id:
                item[f"{user_field}_name"] = entity_names.get(("user", user_id))
        enriched.append(item)
    return enriched


@router.get("/settings", response_model=list[AgentSettingResponse])
async def list_agent_settings(
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    setting_repository: AgentSettingRepository = Depends(get_setting_repository),
):
    return await _ensure_agent_settings(setting_repository)


@router.patch("/settings/{agent_type}", response_model=AgentSettingResponse)
async def update_agent_setting(
    agent_type: str,
    payload: AgentSettingUpdate,
    current_user: dict = Depends(require_sales_manager_or_admin()),
    setting_repository: AgentSettingRepository = Depends(get_setting_repository),
):
    await _ensure_agent_settings(setting_repository)
    existing = await setting_repository.find_by_agent_type(agent_type)
    update_payload = {
        "enabled": payload.enabled,
        "updated_by": current_user.get("id"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if existing:
        return await setting_repository.update_by_id(existing["id"], update_payload)
    return await setting_repository.create({"agent_type": agent_type, **update_payload})


@router.get("/team-stats")
async def get_agent_team_stats(
    current_user: dict = Depends(require_sales_manager_or_admin()),
    db: Client = Depends(get_db),
):
    return await _build_team_agent_stats(db, current_user)


@router.post("/runs", response_model=AgentRunResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_run(
    payload: AgentRunCreate,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    run_repository: AgentRunRepository = Depends(get_run_repository),
):
    if payload.external_run_id:
        existing = await run_repository.find_by_external_id(str(payload.external_run_id))
        if existing:
            return existing
    return await run_repository.create(payload.model_dump(mode="json"))


@router.get("/runs")
async def list_agent_runs(
    status_filter: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    db: Client = Depends(get_db),
    run_repository: AgentRunRepository = Depends(get_run_repository),
):
    filters = {
        "status": status_filter,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
    }
    current_runs = await run_repository.list(filters=filters, order_by="started_at", order_desc=True)
    legacy_runs = await _list_legacy_ai_runs(db, filters)
    legacy_interactions = await _list_legacy_ai_interactions(db, filters)
    return await _enrich_control_rows(db, _sort_runs([*current_runs, *legacy_runs, *legacy_interactions]))


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    run_id: UUID,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    run_repository: AgentRunRepository = Depends(get_run_repository),
):
    return await run_repository.get_by_id(run_id)


@router.patch("/runs/{run_id}", response_model=AgentRunResponse)
async def update_agent_run(
    run_id: UUID,
    payload: AgentRunUpdate,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    run_repository: AgentRunRepository = Depends(get_run_repository),
):
    update_payload = payload.model_dump(exclude_none=True)
    if payload.status in {"completed", "failed", "cancelled"}:
        update_payload["finished_at"] = datetime.now(timezone.utc).isoformat()
    return await run_repository.update_by_id(run_id, update_payload)


@router.post("/runs/{run_id}/trace", status_code=status.HTTP_201_CREATED)
async def create_run_trace(
    run_id: UUID,
    payload: AgentTraceCreate,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    trace_repository: AgentTraceRepository = Depends(get_trace_repository),
):
    return await trace_repository.create({"run_id": str(run_id), **payload.model_dump(mode="json")})


@router.get("/runs/{run_id}/trace")
async def get_run_trace(
    run_id: UUID,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    db: Client = Depends(get_db),
    run_repository: AgentRunRepository = Depends(get_run_repository),
    trace_repository: AgentTraceRepository = Depends(get_trace_repository),
):
    trace = await trace_repository.list_for_run(run_id)
    if trace:
        return trace
    external_trace = await _list_current_run_trace_by_external_id(db, run_id)
    if external_trace:
        return external_trace
    try:
        current_run = await run_repository.get_by_id(run_id)
    except Exception:
        current_run = None
    if not current_run:
        current_run = await run_repository.find_by_external_id(str(run_id))
    if current_run and current_run.get("id"):
        current_run_id = str(current_run["id"])
        if current_run_id != str(run_id):
            trace = await trace_repository.list_for_run(current_run_id)
            if trace:
                return trace
    legacy_trace = await _list_legacy_run_trace(db, run_id)
    if legacy_trace:
        return legacy_trace
    if current_run and current_run.get("external_run_id"):
        legacy_trace = await _list_legacy_run_trace(db, UUID(str(current_run["external_run_id"])))
        if legacy_trace:
            return legacy_trace
    return await _legacy_interaction_as_trace(db, run_id)


@router.get("/memory/{entity_type}/{entity_id}")
async def get_entity_memory(
    entity_type: str,
    entity_id: UUID,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    db: Client = Depends(get_db),
    action_repository: AgentActionRepository = Depends(get_action_repository),
):
    current_memory = await action_repository.list(
        filters={"entity_type": entity_type, "entity_id": str(entity_id)},
        order_by="created_at",
        order_desc=True,
        limit=25,
    )
    legacy_memory = await _list_legacy_ai_actions(db, entity_type, entity_id)
    return await _enrich_control_rows(db, _sort_memory([*current_memory, *legacy_memory])[:25])


@router.get("/entity-snapshot/{entity_type}/{entity_id}")
async def get_ai_entity_snapshot(
    entity_type: str,
    entity_id: UUID,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    db: Client = Depends(get_db),
):
    table_by_type = {
        "lead": "leads",
        "deal": "deals",
        "user": "agents",
        "agent": "agents",
        "task": "tasks",
        "note": "notes",
        "call": "call_sessions",
    }
    table = table_by_type.get(entity_type.strip().lower())
    if table is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported entity_type")
    rows = await _safe_table_select(db, table, filters={"id": str(entity_id)}, limit=1)
    return rows[0] if rows else {}


@router.get("/approvals")
async def list_pending_approvals(
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    db: Client = Depends(get_db),
    approval_repository: AgentApprovalRepository = Depends(get_approval_repository),
    action_repository: AgentActionRepository = Depends(get_action_repository),
):
    fast_approvals = await _load_pending_approvals_fast(db)
    if fast_approvals is not None:
        return await _enrich_control_rows(db, fast_approvals)
    approvals = await approval_repository.list_pending()
    return await _enrich_approvals_with_actions(approvals, action_repository, db)


@router.get("/control-center")
async def get_control_center_snapshot(
    runs_page: int = Query(default=1, ge=1),
    runs_limit: int = Query(default=25, ge=5, le=100),
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    db: Client = Depends(get_db),
    run_repository: AgentRunRepository = Depends(get_run_repository),
    approval_repository: AgentApprovalRepository = Depends(get_approval_repository),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
):
    """Return the AI Control Center data in one request.

    The frontend used to fire multiple first-load requests at the same time.
    On a cold backend/database connection that made the first page visit prone
    to request timeouts. This snapshot endpoint reuses shared data and avoids
    duplicate round trips.
    """
    filters = {"status": None, "entity_type": None, "entity_id": None}
    offset = (runs_page - 1) * runs_limit
    source_window = offset + runs_limit + 1
    await _ensure_ai_agent_registry(ai_agent_repo)

    fast_snapshot = await _load_control_center_snapshot_fast(
        db,
        runs_limit=runs_limit,
        source_window=source_window,
    )
    if fast_snapshot is not None:
        sorted_runs = _sort_runs(fast_snapshot["runs"])
        paged_runs = sorted_runs[offset:offset + runs_limit]
        runs_count = len(paged_runs)
        enriched_rows = await _enrich_control_rows(db, [*paged_runs, *fast_snapshot["approvals"]])
        runs = enriched_rows[:runs_count]
        approvals = enriched_rows[runs_count:]
        return {
            "runs": runs,
            "runs_pagination": {
                "page": runs_page,
                "limit": runs_limit,
                "has_more": len(sorted_runs) > offset + runs_limit,
            },
            "metrics": {
                "running": int(fast_snapshot.get("metrics", {}).get("running") or 0),
                "failed": int(fast_snapshot.get("metrics", {}).get("failed") or 0),
                "completed": int(fast_snapshot.get("metrics", {}).get("completed") or 0),
                "pending_approvals": len(approvals),
                "total_runs": int(fast_snapshot.get("metrics", {}).get("total_runs") or 0),
            },
            "approvals": approvals,
            "ai_agents": _build_ai_agent_rows(fast_snapshot["agents"], _sort_runs(fast_snapshot["agent_runs"]), fast_snapshot["actions"]),
        }

    current_runs = await run_repository.list(limit=source_window, order_by="started_at", order_desc=True)
    legacy_runs = await _list_legacy_ai_runs(db, filters, limit=source_window)
    legacy_interactions = await _list_legacy_ai_interactions(db, filters, limit=source_window)
    sorted_runs = _sort_runs([*current_runs, *legacy_runs, *legacy_interactions])
    paged_runs = sorted_runs[offset:offset + runs_limit]
    runs = await _enrich_control_rows(db, paged_runs)

    approvals = await _enrich_approvals_with_actions(await approval_repository.list_pending(), get_action_repository(db), db)
    agents = await _ensure_ai_agent_registry(ai_agent_repo)
    actions = await _safe_table_select(db, "ai_agent_actions", order_by="created_at", order_desc=True, limit=1000)
    agent_runs = await run_repository.list(limit=5000, order_by="started_at", order_desc=True)

    return {
        "runs": runs,
        "runs_pagination": {
            "page": runs_page,
            "limit": runs_limit,
            "has_more": len(sorted_runs) > offset + runs_limit,
        },
        "metrics": _build_control_center_metrics(sorted_runs, approvals),
        "approvals": approvals,
        "ai_agents": _build_ai_agent_rows(agents, agent_runs or sorted_runs, actions),
    }


@router.post("/approvals/{approval_id}/approve")
async def approve_agent_action(
    approval_id: UUID,
    decision: AgentApprovalDecision | None = None,
    current_user: dict = Depends(require_sales_manager_or_admin()),
    approval_repository: AgentApprovalRepository = Depends(get_approval_repository),
    action_repository: AgentActionRepository = Depends(get_action_repository),
    task_repository: TaskRepository = Depends(get_task_repository),
    note_repository: NoteRepository = Depends(get_note_repository),
    notification_service: NotificationService = Depends(get_notification_service),
):
    approval = await approval_repository.get_by_id(approval_id)
    if approval.get("state") != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is already decided")

    action = await action_repository.get_by_id(approval["action_id"])
    if str(action.get("action_type") or "").strip().lower() == "create_task":
        if not decision or not decision.due_at:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Task approval requires a deadline")
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        payload = {**payload, "due_at": decision.due_at.isoformat()}
        action = await action_repository.update_by_id(action["id"], {"payload": payload})
    created = await _dispatch_stored_action(
        action,
        current_user=current_user,
        task_repository=task_repository,
        note_repository=note_repository,
        notification_service=notification_service,
    )
    await action_repository.mark_dispatched(
        action["id"],
        crm_record_type=created["record_type"],
        crm_record_id=created["id"],
    )
    await approval_repository.update_by_id(
        approval_id,
        {
            "state": "approved",
            "approver_id": current_user.get("id"),
            "approver_note": (decision.note if decision else None),
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"status": "approved", "action_id": action["id"], "id": created["id"]}


@router.post("/approvals/{approval_id}/reject")
async def reject_agent_action(
    approval_id: UUID,
    decision: AgentApprovalDecision | None = None,
    current_user: dict = Depends(require_sales_manager_or_admin()),
    approval_repository: AgentApprovalRepository = Depends(get_approval_repository),
    action_repository: AgentActionRepository = Depends(get_action_repository),
):
    approval = await approval_repository.get_by_id(approval_id)
    if approval.get("state") != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is already decided")

    await action_repository.update_by_id(
        approval["action_id"],
        {"approval_status": "rejected", "dispatch_status": "rejected"},
    )
    await approval_repository.update_by_id(
        approval_id,
        {
            "state": "rejected",
            "approver_id": current_user.get("id"),
            "approver_note": (decision.note if decision else None),
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"status": "rejected", "action_id": approval["action_id"]}


@router.post("/actions", response_model=AgentActionResponse, status_code=status.HTTP_202_ACCEPTED)
async def dispatch_agent_action(
    payload: AgentActionIn,
    current_user: dict = Depends(require_human_or_ai_agent_auth),
    db: Client = Depends(get_db),
    run_repository: AgentRunRepository = Depends(get_run_repository),
    action_repository: AgentActionRepository = Depends(get_action_repository),
    approval_repository: AgentApprovalRepository = Depends(get_approval_repository),
    task_repository: TaskRepository = Depends(get_task_repository),
    note_repository: NoteRepository = Depends(get_note_repository),
    notification_service: NotificationService = Depends(get_notification_service),
):
    _validate_action_payload(payload)
    existing = await _find_existing_action(payload, action_repository)
    if existing:
        return AgentActionResponse(
            status="pending_approval" if existing.get("approval_status") == "pending" else "created",
            action_type=existing["action_type"],
            action_id=str(existing["id"]),
            id=str(existing.get("crm_record_id")) if existing.get("crm_record_id") else None,
        )

    run_id = await _resolve_run_id(payload, run_repository)
    needs_approval = _requires_approval(payload)
    human_actor_id = _human_actor_id(payload.data, current_user)
    action = await action_repository.create(
        {
            "run_id": run_id,
            "external_run_id": payload.run_id,
            "action_type": payload.action_type.strip().lower(),
            "entity_type": payload.entity_type,
            "entity_id": str(payload.entity_id),
            "reason": payload.reason,
            "payload": payload.data,
            "idempotency_key": payload.idempotency_key,
            "approval_status": "pending" if needs_approval else "auto_approved",
            "dispatch_status": "not_dispatched",
            "created_by": human_actor_id,
        }
    )

    if needs_approval:
        approval = await approval_repository.create(
            {
                "action_id": action["id"],
                "state": "pending",
                "requested_by": human_actor_id,
                "reason": payload.reason,
            }
        )
        await _notify_approval_recipients(
            db=db,
            notification_service=notification_service,
            action=action,
            approval_id=str(approval["id"]),
            actor_id=human_actor_id,
        )
        return AgentActionResponse(
            status="pending_approval",
            action_type=payload.action_type,
            action_id=str(action["id"]),
            approval_id=str(approval["id"]),
        )

    created = await _dispatch_payload_action(
        payload,
        agent_action_id=str(action["id"]),
        current_user=current_user,
        task_repository=task_repository,
        note_repository=note_repository,
        notification_service=notification_service,
    )
    await action_repository.mark_dispatched(
        action["id"],
        crm_record_type=created["record_type"],
        crm_record_id=created["id"],
    )
    return AgentActionResponse(
        status="created",
        action_type=payload.action_type,
        action_id=str(action["id"]),
        id=created["id"],
    )


async def _resolve_run_id(payload: AgentActionIn, run_repository: AgentRunRepository) -> str | None:
    if not payload.run_id:
        return None
    try:
        existing = await run_repository.find_by_external_id(payload.run_id)
    except Exception:
        existing = None
    if existing:
        return str(existing["id"])
    try:
        created = await run_repository.create(
            {
                "external_run_id": payload.run_id,
                "trigger_type": "agent_action_callback",
                "entity_id": str(payload.entity_id),
                "entity_type": payload.entity_type,
                "status": "running",
                "event_payload": {},
            }
        )
        return str(created["id"])
    except Exception:
        return None


async def _find_existing_action(
    payload: AgentActionIn,
    action_repository: AgentActionRepository,
) -> dict | None:
    if not payload.idempotency_key:
        return None
    return await action_repository.find_one(filters={"idempotency_key": payload.idempotency_key})


def _validate_action_payload(payload: AgentActionIn) -> None:
    action_type = payload.action_type.strip().lower()
    if action_type not in SUPPORTED_ACTIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action_type")
    data = payload.data or {}
    if action_type == "create_task" and not data.get("title"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="create_task requires title")
    if action_type == "create_note" and not (data.get("content") or data.get("title")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="create_note requires content or title")
    if action_type == "create_alert" and not data.get("recipient_id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="create_alert requires recipient_id")


def _requires_approval(payload: AgentActionIn) -> bool:
    action_type = payload.action_type.strip().lower()
    if payload.approval_status == "approved":
        return False
    if payload.requires_approval is True:
        return True
    return action_type in RISKY_ACTIONS


def _human_actor_id(data: dict | None, current_user: dict) -> str | None:
    data = data or {}
    for key in ("assigned_to", "actor_id", "created_by", "owner_id"):
        value = data.get(key)
        if value:
            return str(value)
    role = str(current_user.get("role") or "").lower()
    if role in {"admin", "sales_manager", "manager", "sales_rep"} and current_user.get("id"):
        return str(current_user.get("id"))
    return None


def _compact_task_description(description: object, note_content: object = None) -> tuple[str | None, str | None]:
    text = str(description or "").strip()
    note_text = str(note_content or "").strip()
    if not text:
        return None, note_text or None

    is_verbose = len(text) > 260 or "\n" in text or text.count("- ") > 0 or text.count("* ") > 0
    if not is_verbose:
        return text, note_text or None

    cleaned_lines = [
        line.strip().lstrip("-* ").strip()
        for line in text.splitlines()
        if line.strip()
    ]
    compact = cleaned_lines[0] if cleaned_lines else text
    if len(compact) > 180:
        compact = compact[:177].rstrip() + "..."
    details = note_text or text
    return compact, details


async def _notify_approval_recipients(
    *,
    db: Client,
    notification_service: NotificationService,
    action: dict,
    approval_id: str,
    actor_id: str | None,
) -> None:
    payload = action.get("payload") or {}
    title = str(payload.get("title") or action.get("action_type") or "AI action")
    reason = str(action.get("reason") or "An AI workflow requires approval.")
    if not hasattr(db, "engine"):
        return

    def _query_recipients():
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id
                    FROM agents
                    WHERE COALESCE(is_active, true) = true
                      AND LOWER(COALESCE(role, '')) IN ('admin', 'manager', 'sales_manager')
                    """
                )
            ).mappings().all()
            return [str(row["id"]) for row in rows if row.get("id")]

    recipient_ids = await run_db_operation(_query_recipients)
    for recipient_id in recipient_ids:
        await notification_service.create_notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            type="agent_approval",
            title=f"AI approval required: {title}",
            message=f"{reason.rstrip('. ')}. Review in the AI Control Center.",
            entity_type=str(action.get("entity_type") or ""),
            entity_id=str(action.get("entity_id") or ""),
        )


async def _dispatch_payload_action(
    payload: AgentActionIn,
    *,
    agent_action_id: str | None = None,
    current_user: dict,
    task_repository: TaskRepository,
    note_repository: NoteRepository,
    notification_service: NotificationService,
) -> dict[str, str | None]:
    return await _dispatch_action_data(
        action_type=payload.action_type,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        reason=payload.reason,
        data=payload.data,
        current_user=current_user,
        task_repository=task_repository,
        note_repository=note_repository,
        notification_service=notification_service,
        agent_action_id=agent_action_id,
    )


async def _dispatch_stored_action(
    action: dict,
    *,
    current_user: dict,
    task_repository: TaskRepository,
    note_repository: NoteRepository,
    notification_service: NotificationService,
) -> dict[str, str | None]:
    return await _dispatch_action_data(
        action_type=action["action_type"],
        entity_type=action["entity_type"],
        entity_id=UUID(str(action["entity_id"])),
        reason=action["reason"],
        data=action["payload"] or {},
        current_user=current_user,
        task_repository=task_repository,
        note_repository=note_repository,
        notification_service=notification_service,
        agent_action_id=str(action.get("id")) if action.get("id") else None,
    )


async def _dispatch_action_data(
    *,
    action_type: str,
    entity_type: str,
    entity_id: UUID,
    reason: str,
    data: dict,
    current_user: dict,
    task_repository: TaskRepository,
    note_repository: NoteRepository,
    notification_service: NotificationService,
    agent_action_id: str | None = None,
) -> dict[str, str | None]:
    action_type = action_type.strip().lower()
    if action_type == "create_task":
        assigned_to = data.get("assigned_to") or data.get("actor_id") or data.get("created_by")
        description, note_content = _compact_task_description(data.get("description"), data.get("note_content"))
        task_payload = TaskCreate(
            entity_type=entity_type,
            entity_id=entity_id,
            title=str(data.get("title")),
            description=description,
            assigned_to=assigned_to,
            status=data.get("status") or "backlog",
            priority=data.get("priority") or "medium",
            due_at=_parse_datetime(data.get("due_at")),
            source="ai",
            ai_reason=reason,
            ai_action_id=UUID(str(agent_action_id)) if agent_action_id else None,
        )
        created = await task_repository.create(task_payload.model_dump())
        created_id = str(created.get("id")) if created.get("id") else None
        actor_id = _human_actor_id(data, current_user)
        if note_content:
            note_payload = NoteCreate(
                entity_type=entity_type,
                entity_id=entity_id,
                content=note_content,
                author_id=UUID(str(actor_id)) if actor_id else None,
                source="ai",
                ai_reason="Meeting details captured from transcript",
                ai_action_id=UUID(str(agent_action_id)) if agent_action_id else None,
            )
            await note_repository.create(note_payload.model_dump())
        if assigned_to:
            await notification_service.create_notification(
                recipient_id=str(assigned_to),
                actor_id=actor_id,
                type="task_assigned",
                title="AI task assigned to you",
                message=f"AI created task \"{created.get('title') or data.get('title') or 'Untitled Task'}\" from a meeting.",
                entity_type="task",
                entity_id=created_id,
            )
        return {"record_type": "task", "id": created_id}

    if action_type == "create_note":
        note_payload = NoteCreate(
            entity_type=entity_type,
            entity_id=entity_id,
            content=str(data.get("content") or data.get("title") or reason),
            author_id=UUID(str(_human_actor_id(data, current_user))) if _human_actor_id(data, current_user) else None,
            source="ai",
            ai_reason=reason,
            ai_action_id=UUID(str(agent_action_id)) if agent_action_id else None,
        )
        created = await note_repository.create(note_payload.model_dump())
        return {"record_type": "note", "id": str(created.get("id")) if created.get("id") else None}

    if action_type == "create_alert":
        created = await notification_service.create_notification(
            recipient_id=str(data.get("recipient_id")),
            actor_id=str(current_user.get("id") or ""),
            type="agent_alert",
            title=str(data.get("title") or "Agent alert"),
            message=str(data.get("message") or reason),
            entity_type=entity_type,
            entity_id=str(entity_id),
        )
        return {"record_type": "notification", "id": str(created.get("id")) if created else None}

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action_type")


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _safe_table_select(
    db: Client,
    table_name: str,
    *,
    filters: dict[str, object] | None = None,
    order_by: str | None = None,
    order_desc: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    try:
        query = db.table(table_name).select("*")
        for column, value in (filters or {}).items():
            if value is not None:
                query = query.eq(column, value)
        if order_by:
            query = query.order(order_by, desc=order_desc)
        if limit:
            if offset > 0:
                query = query.range(offset, offset + limit - 1)
            else:
                query = query.limit(limit)
        response = await run_db_operation(lambda: query.execute())
        return response.data or []
    except Exception:
        return []


async def _list_legacy_ai_runs(db: Client, filters: dict[str, object], *, limit: int = 100) -> list[dict]:
    rows = await _safe_table_select(
        db,
        "ai_runs",
        filters={
            "status": filters.get("status"),
            "entity_type": filters.get("entity_type"),
            "entity_id": filters.get("entity_id"),
        },
        order_by="started_at",
        order_desc=True,
        limit=limit,
    )
    return [
        {
            "id": row.get("id"),
            "external_run_id": row.get("id"),
            "trigger_type": row.get("trigger_type") or "legacy_ai_run",
            "entity_id": row.get("entity_id"),
            "entity_type": row.get("entity_type"),
            "status": row.get("status") or "unknown",
            "summary": row.get("summary"),
            "failure_cause": row.get("failure_cause"),
            "failure_detail": row.get("failure_detail"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "legacy_source": "ai_service.ai_runs",
        }
        for row in rows
    ]


async def _list_legacy_ai_interactions(db: Client, filters: dict[str, object], *, limit: int = 100) -> list[dict]:
    if filters.get("status") or filters.get("entity_type") or filters.get("entity_id"):
        return []
    rows = await _safe_table_select(db, "ai_interactions", order_by="created_at", order_desc=True, limit=limit)
    return [
        {
            "id": row.get("id"),
            "external_run_id": row.get("id"),
            "trigger_type": row.get("interaction_type") or "legacy_ai_interaction",
            "entity_id": row.get("ticket_id") or row.get("id"),
            "entity_type": "ticket" if row.get("ticket_id") else "ai_interaction",
            "status": "completed",
            "summary": _truncate(row.get("response") or row.get("prompt") or ""),
            "started_at": row.get("created_at"),
            "finished_at": row.get("created_at"),
            "legacy_source": "backend.ai_interactions",
        }
        for row in rows
    ]


async def _list_legacy_run_trace(db: Client, run_id: UUID) -> list[dict]:
    rows = await _safe_table_select(
        db,
        "ai_run_traces",
        filters={"run_id": str(run_id)},
        order_by="created_at",
        limit=100,
    )
    return [
        {
            "id": row.get("id"),
            "run_id": row.get("run_id"),
            "step": row.get("step"),
            "status": row.get("status") or "completed",
            "payload": row.get("payload") or {},
            "created_at": row.get("created_at"),
            "legacy_source": "ai_service.ai_run_traces",
        }
        for row in rows
    ]


async def _list_current_run_trace_by_external_id(db: Client, external_run_id: UUID) -> list[dict]:
    rows = await _safe_table_select(
        db,
        "ai_agent_run_traces",
        filters={"external_run_id": str(external_run_id)},
        order_by="created_at",
        limit=100,
    )
    return [
        {
            "id": row.get("id"),
            "run_id": row.get("run_id"),
            "external_run_id": row.get("external_run_id"),
            "step": row.get("step"),
            "status": row.get("status") or "completed",
            "payload": row.get("payload") or {},
            "created_at": row.get("created_at"),
        }
        for row in rows
    ]


async def _legacy_interaction_as_trace(db: Client, run_id: UUID) -> list[dict]:
    rows = await _safe_table_select(db, "ai_interactions", filters={"id": str(run_id)}, limit=1)
    if not rows:
        return []
    row = rows[0]
    return [
        {
            "id": f"{row.get('id')}:prompt",
            "run_id": row.get("id"),
            "step": "legacy_prompt_response",
            "status": "completed",
            "payload": {
                "interaction_type": row.get("interaction_type"),
                "prompt": row.get("prompt"),
                "response": row.get("response"),
                "model_used": row.get("model_used"),
                "tokens_used": row.get("tokens_used"),
            },
            "created_at": row.get("created_at"),
            "legacy_source": "backend.ai_interactions",
        }
    ]


async def _list_legacy_ai_actions(db: Client, entity_type: str, entity_id: UUID) -> list[dict]:
    rows = await _safe_table_select(
        db,
        "ai_actions",
        filters={"entity_type": entity_type, "entity_id": str(entity_id)},
        order_by="created_at",
        order_desc=True,
        limit=25,
    )
    return [
        {
            "id": row.get("id"),
            "run_id": row.get("run_id"),
            "action_type": row.get("action_type"),
            "entity_type": row.get("entity_type"),
            "entity_id": row.get("entity_id"),
            "reason": row.get("reason"),
            "payload": row.get("payload") or {},
            "approval_status": row.get("approval_status"),
            "dispatch_status": "legacy",
            "created_at": row.get("created_at"),
            "legacy_source": "ai_service.ai_actions",
        }
        for row in rows
    ]


def _sort_runs(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda item: str(item.get("started_at") or ""), reverse=True)


def _sort_memory(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def _truncate(value: object, limit: int = 180) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}..."


async def _ensure_agent_settings(setting_repository: AgentSettingRepository) -> list[dict]:
    defaults = [
        ("lead_assistant", True),
        ("deal_risk_watcher", True),
        ("daily_summary_assistant", True),
        ("task_deadline_watcher", True),
    ]
    existing = await setting_repository.list_settings()
    by_type = {item.get("agent_type"): item for item in existing}
    for agent_type, enabled in defaults:
        if agent_type not in by_type:
            created = await setting_repository.create({"agent_type": agent_type, "enabled": enabled})
            by_type[agent_type] = created
    return sorted(by_type.values(), key=lambda item: str(item.get("agent_type") or ""))


async def _ensure_ai_agent_registry(ai_agent_repo: AiAgentRepository) -> list[dict]:
    existing = await ai_agent_repo.list_all()
    by_key = {str(item.get("agent_key") or ""): item for item in existing}
    for payload in DEFAULT_AI_AGENT_REGISTRY:
        agent_key = payload["agent_key"]
        if agent_key not in by_key:
            created = await ai_agent_repo.create(payload)
            by_key[agent_key] = created
    return sorted(by_key.values(), key=lambda item: str(item.get("display_name") or ""))


async def _build_team_agent_stats(db: Client, current_user: dict) -> dict:
    user_id = str(current_user.get("id") or "")
    role = str(current_user.get("role") or "").lower()
    agents = await _safe_table_select(db, "agents", limit=500)
    team_members = await _safe_table_select(db, "team_members", limit=1000)
    teams = await _safe_table_select(db, "teams", limit=500)
    actions = await _safe_table_select(db, "ai_agent_actions", order_by="created_at", order_desc=True, limit=1000)
    approvals = await _safe_table_select(db, "ai_agent_approval_requests", order_by="created_at", order_desc=True, limit=1000)
    runs = await _safe_table_select(db, "ai_agent_runs", order_by="started_at", order_desc=True, limit=1000)

    manager_team_ids = {
        str(team.get("id"))
        for team in teams
        if str(team.get("manager_id")) == user_id
    }
    managed_agent_ids = {
        str(member.get("agent_id"))
        for member in team_members
        if str(member.get("team_id")) in manager_team_ids
    }
    if role == "admin":
        visible_agents = agents
    else:
        visible_agents = [agent for agent in agents if str(agent.get("id")) in managed_agent_ids or str(agent.get("id")) == user_id]

    reps = [agent for agent in visible_agents if str(agent.get("role") or "").lower() in {"sales_rep", "sales_manager", "manager"}]
    rep_rows = []
    for agent in reps:
        agent_id = str(agent.get("id"))
        agent_actions = [action for action in actions if _action_belongs_to_agent(action, agent_id)]
        agent_approvals = [approval for approval in approvals if str(approval.get("requested_by")) == agent_id or str(approval.get("approver_id")) == agent_id]
        agent_runs = [
            run
            for run in runs
            if str(run.get("entity_type")) == "user" and str(run.get("entity_id")) == agent_id
        ]
        rep_rows.append(
            {
                "agent_id": agent_id,
                "name": agent.get("full_name") or agent.get("email") or "Agent",
                "email": agent.get("email"),
                "role": agent.get("role"),
                "team_id": agent.get("team_id"),
                "actions": len(agent_actions),
                "pending_actions": sum(1 for action in agent_actions if action.get("approval_status") == "pending"),
                "approved_actions": sum(1 for action in agent_actions if action.get("approval_status") in {"approved", "auto_approved"}),
                "rejected_actions": sum(1 for action in agent_actions if action.get("approval_status") == "rejected"),
                "approval_decisions": len(agent_approvals),
                "daily_summaries": len(agent_runs),
                "last_activity_at": _latest_timestamp([*agent_actions, *agent_approvals, *agent_runs]),
            }
        )

    return {
        "scope": "admin" if role == "admin" else "manager",
        "teams": [
            team
            for team in teams
            if role == "admin" or str(team.get("id")) in manager_team_ids
        ],
        "agents": sorted(rep_rows, key=lambda item: str(item.get("last_activity_at") or ""), reverse=True),
        "totals": {
            "agents": len(rep_rows),
            "actions": sum(row["actions"] for row in rep_rows),
            "pending_actions": sum(row["pending_actions"] for row in rep_rows),
            "daily_summaries": sum(row["daily_summaries"] for row in rep_rows),
        },
    }


def _action_belongs_to_agent(action: dict, agent_id: str) -> bool:
    payload = action.get("payload") or {}
    return (
        str(action.get("created_by")) == agent_id
        or str(payload.get("assigned_to")) == agent_id
        or str(payload.get("recipient_id")) == agent_id
    )


def _latest_timestamp(rows: list[dict]) -> str | None:
    values = [
        str(row.get("created_at") or row.get("started_at") or row.get("decided_at") or "")
        for row in rows
    ]
    values = [value for value in values if value]
    return max(values) if values else None


def _build_ai_agent_rows(agents: list[dict], runs: list[dict], actions: list[dict]) -> list[dict]:
    result = []
    for agent in agents:
        agent_key = str(agent.get("agent_key") or "").lower()
        if agent_key not in IMPLEMENTED_AI_AGENT_KEYS:
            continue

        agent_type = str(agent.get("agent_type") or "").lower()
        aliases = {
            agent_key,
            agent_type,
            *AI_AGENT_RUNTIME_ALIASES.get(agent_key, set()),
        }
        aliases = {alias for alias in aliases if alias}

        agent_runs = [
            run for run in runs
            if str(run.get("trigger_type") or "").lower() in aliases
            or any(alias in str(run.get("summary") or "").lower() for alias in aliases)
        ]
        run_ids = {str(run.get("id")) for run in agent_runs if run.get("id")}
        agent_actions = [
            action for action in actions
            if str(action.get("run_id") or "") in run_ids
            or any(alias in str(action.get("reason") or "").lower() for alias in aliases)
            or any(alias in str(action.get("action_type") or "").lower() for alias in aliases)
        ]
        last_seen_at = agent.get("last_seen_at") or _latest_timestamp([*agent_runs, *agent_actions])
        result.append({
            **agent,
            "runtime_aliases": sorted(aliases),
            "is_wired": True,
            "total_runs": len(agent_runs),
            "total_actions": len(agent_actions),
            "pending_actions": sum(1 for action in agent_actions if action.get("approval_status") == "pending"),
            "last_seen_at": last_seen_at,
        })
    return result


# ===========================================================================
# AI Agents Registry Endpoints
# Human CRM users -> /api/agent/team-stats
# AI workers      -> /api/agent/ai-agents  (these endpoints)
# ===========================================================================

@router.get("/ai-agents")
async def list_ai_agents(
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
    db=Depends(get_db),
):
    """Return AI service-backed agents with run/action stats.

    The registry table may contain future placeholder identities. The control
    center should show the workers that are actually wired to the AI service so
    the page behaves like one application instead of a disconnected name list.
    """
    agents = await _ensure_ai_agent_registry(ai_agent_repo)

    actions = await _safe_table_select(db, "ai_agent_actions", order_by="created_at", order_desc=True, limit=2000)
    runs = await _safe_table_select(db, "ai_agent_runs", order_by="started_at", order_desc=True, limit=2000)

    return _build_ai_agent_rows(agents, runs, actions)


@router.patch("/ai-agents/{agent_key}")
async def update_ai_agent(
    agent_key: str,
    payload: AiAgentUpdate,
    _current_user: dict = Depends(require_sales_manager_or_admin()),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
    setting_repository: AgentSettingRepository = Depends(get_setting_repository),
):
    """Enable/disable or update metadata of a registered AI agent."""
    agent = await ai_agent_repo.find_by_key(agent_key)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI agent not found")

    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        return agent

    now = datetime.now(timezone.utc).isoformat()
    update_data["updated_at"] = now
    updated_agent = await ai_agent_repo.update_by_id(agent["id"], update_data)

    if "enabled" in update_data:
        enabled = bool(update_data["enabled"])
        normalized_agent_key = str(agent.get("agent_key") or agent_key or "").lower()
        setting_keys = {
            str(agent.get("agent_type") or ""),
            normalized_agent_key,
            *AI_AGENT_RUNTIME_ALIASES.get(normalized_agent_key, set()),
        }
        for setting_key in {key for key in setting_keys if key}:
            existing = await setting_repository.find_by_agent_type(setting_key)
            setting_payload = {
                "enabled": enabled,
                "updated_by": _current_user.get("id"),
                "updated_at": now,
            }
            if existing:
                await setting_repository.update_by_id(existing["id"], setting_payload)
            else:
                await setting_repository.create({"agent_type": setting_key, **setting_payload})

    return updated_agent


# ---------------------------------------------------------------------------
# AI Agent Credentials  (admin only — for AI service authentication)
# ---------------------------------------------------------------------------

@router.get("/service-credentials")
async def list_ai_service_credentials(
    _current_user: dict = Depends(require_admin()),
    db: Client = Depends(get_db),
):
    """List AI service credentials without exposing raw tokens or hashes."""
    response = await run_db_operation(
        lambda: db.table("ai_agent_credentials")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return [{k: v for k, v in row.items() if k != "token_hash"} for row in (response.data or [])]


@router.post("/service-credentials", status_code=status.HTTP_201_CREATED)
async def create_ai_service_credential(
    payload: AiAgentCredentialCreate,
    current_user: dict = Depends(require_admin()),
    cred_repo: AiAgentCredentialRepository = Depends(get_ai_agent_credential_repository),
):
    """
    Issue a new global service token for the AI service.
    The raw_token is returned ONCE; only its hash is stored.
    """
    from datetime import timedelta

    raw_token, key_prefix, token_hash = generate_ai_service_token()

    expires_at = None
    if payload.expires_in_days:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)).isoformat()

    cred = await cred_repo.create({
        "ai_agent_id": None,
        "key_prefix":  key_prefix,
        "token_hash":  token_hash,
        "scopes":      payload.scopes,
        "is_active":   True,
        "expires_at":  expires_at,
        "created_by":  str(current_user["id"]) if current_user.get("id") else None,
    })

    return {**{k: v for k, v in cred.items() if k != "token_hash"}, "raw_token": raw_token}


@router.delete("/service-credentials/{credential_id}", status_code=status.HTTP_200_OK)
async def revoke_ai_service_credential(
    credential_id: UUID,
    _current_user: dict = Depends(require_admin()),
    cred_repo: AiAgentCredentialRepository = Depends(get_ai_agent_credential_repository),
):
    """Revoke a global service credential so it can no longer authenticate."""
    await cred_repo.update_by_id(
        credential_id,
        {
            "is_active":  False,
            "revoked_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"status": "revoked", "credential_id": str(credential_id)}


@router.get("/ai-agents/{agent_key}/credentials")
async def list_ai_agent_credentials(
    agent_key: str,
    _current_user: dict = Depends(require_admin()),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
    cred_repo: AiAgentCredentialRepository = Depends(get_ai_agent_credential_repository),
):
    """List credentials (without raw tokens) for an AI agent."""
    agent = await ai_agent_repo.find_by_key(agent_key)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI agent not found")
    creds = await cred_repo.list_for_agent(str(agent["id"]))
    # Never expose token_hash in the response
    return [{k: v for k, v in c.items() if k != "token_hash"} for c in creds]


@router.post("/ai-agents/{agent_key}/credentials", status_code=status.HTTP_201_CREATED)
async def create_ai_agent_credential(
    agent_key: str,
    payload: AiAgentCredentialCreate,
    current_user: dict = Depends(require_admin()),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
    cred_repo: AiAgentCredentialRepository = Depends(get_ai_agent_credential_repository),
):
    """
    Legacy endpoint: issue a service token through an agent-specific URL.
    New UI should use /service-credentials so tokens are service-scoped.
    The raw_token is returned ONCE — store it securely; it cannot be retrieved again.
    """
    from datetime import timedelta

    agent = await ai_agent_repo.find_by_key(agent_key)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI agent not found")

    raw_token, key_prefix, token_hash = generate_ai_service_token()

    expires_at = None
    if payload.expires_in_days:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)).isoformat()

    cred = await cred_repo.create({
        "ai_agent_id": None,
        "key_prefix":  key_prefix,
        "token_hash":  token_hash,
        "scopes":      payload.scopes,
        "is_active":   True,
        "expires_at":  expires_at,
        "created_by":  str(current_user["id"]) if current_user.get("id") else None,
    })

    return {**{k: v for k, v in cred.items() if k != "token_hash"}, "raw_token": raw_token}


@router.delete("/ai-agents/{agent_key}/credentials/{credential_id}", status_code=status.HTTP_200_OK)
async def revoke_ai_agent_credential(
    agent_key: str,
    credential_id: UUID,
    _current_user: dict = Depends(require_admin()),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
    cred_repo: AiAgentCredentialRepository = Depends(get_ai_agent_credential_repository),
):
    """Revoke a service credential so it can no longer authenticate."""
    agent = await ai_agent_repo.find_by_key(agent_key)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI agent not found")

    await cred_repo.update_by_id(
        credential_id,
        {
            "is_active":  False,
            "revoked_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"status": "revoked", "credential_id": str(credential_id)}


# ---------------------------------------------------------------------------
# AI Service callback endpoint  (authenticated with AI agent credentials)
# ---------------------------------------------------------------------------

@router.post("/ai-service/heartbeat", status_code=status.HTTP_200_OK)
async def ai_service_heartbeat(
    ai_agent: dict = Depends(require_ai_agent_auth),
):
    """
    Heartbeat endpoint for AI services to confirm connectivity.
    Authenticated with X-AI-Agent-Key + X-AI-Service-Token headers.
    Updates last_seen_at automatically via the auth dependency.
    """
    return {
        "status": "ok",
        "agent_key":  ai_agent.get("agent_key"),
        "agent_type": ai_agent.get("agent_type"),
        "scopes":     ai_agent.get("credential_scopes"),
    }


@router.post("/leads/score/sweep", status_code=status.HTTP_202_ACCEPTED)
async def ai_service_lead_score_sweep(
    background_tasks: BackgroundTasks,
    limit: int = 100,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    db: Client = Depends(get_db),
):
    """
    Recalculate lead scores from the AI service scheduler.

    This lets the AI worker refresh scores without a user opening each lead
    detail page or pressing the manual scoring button.
    """
    return await queue_lead_score_sweep(background_tasks, db, limit=limit)


@router.get("/tasks/deadline-candidates", response_model=TaskDeadlineCandidateList, status_code=status.HTTP_200_OK)
async def ai_service_task_deadline_candidates(
    limit: int = Query(default=100, ge=1, le=500),
    _ai_agent: dict = Depends(require_ai_agent_auth),
    service: TaskDeadlineService = Depends(get_task_deadline_service),
):
    """Return due-soon and overdue task rows for the deadline watch agent."""
    return {"items": await service.list_candidates(limit=limit)}


@router.post("/tasks/deadline-alerts", response_model=TaskDeadlineAlertResponse, status_code=status.HTTP_201_CREATED)
async def ai_service_record_task_deadline_alert(
    payload: TaskDeadlineAlertIn,
    _ai_agent: dict = Depends(require_ai_agent_auth),
    service: TaskDeadlineService = Depends(get_task_deadline_service),
):
    """Record an AI deadline alert/output with dedupe semantics."""
    return await service.record_alert(payload)


@router.post("/tasks/deadline-sweep", status_code=status.HTTP_202_ACCEPTED)
async def ai_service_task_deadline_sweep(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=100, ge=1, le=500),
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    service: TaskDeadlineService = Depends(get_task_deadline_service),
):
    """Queue the deterministic task deadline notification sweep."""
    background_tasks.add_task(service.process_due_alerts, limit=limit)
    return {"status": "queued", "limit": limit}


@router.get("/users/summary-candidates", status_code=status.HTTP_200_OK)
async def ai_service_summary_candidates(
    limit: int = Query(default=500, ge=1, le=1000),
    _ai_agent: dict = Depends(require_ai_agent_auth),
    db: Client = Depends(get_db),
):
    """Return active CRM users that should receive scheduled AI summaries."""
    rows = await _safe_table_select(db, "agents", order_by="created_at", order_desc=True, limit=limit)
    return [
        {
            "id": row.get("id"),
            "full_name": row.get("full_name") or row.get("name"),
            "name": row.get("name") or row.get("full_name"),
            "email": row.get("email"),
            "role": row.get("role"),
            "status": row.get("status"),
            "is_active": row.get("is_active", True),
        }
        for row in rows
        if row.get("id") and row.get("is_active", True) is not False
    ]


@router.get("/ai-agents/runtime", status_code=status.HTTP_200_OK)
async def ai_service_runtime_agents(
    _ai_agent: dict = Depends(require_ai_agent_auth),
    ai_agent_repo: AiAgentRepository = Depends(get_ai_agent_repository),
):
    """Return enabled AI runtime identities for service-side orchestration."""
    agents = await ai_agent_repo.list_enabled()
    return [
        {
            "id": row.get("id"),
            "agent_key": row.get("agent_key"),
            "display_name": row.get("display_name"),
            "description": row.get("description"),
            "agent_type": row.get("agent_type"),
            "status": row.get("status"),
            "enabled": row.get("enabled"),
            "capabilities": row.get("capabilities") or [],
            "config": row.get("config") or {},
            "service_url": row.get("service_url"),
            "last_seen_at": row.get("last_seen_at"),
        }
        for row in agents
    ]


@router.get("/leads/stale-candidates", status_code=status.HTTP_200_OK)
async def ai_service_stale_lead_candidates(
    limit: int = Query(default=500, ge=1, le=1000),
    _ai_agent: dict = Depends(require_ai_agent_auth),
    db: Client = Depends(get_db),
):
    """Return lead rows the AI service can evaluate for stale-follow-up nudges."""
    rows = await _safe_table_select(db, "leads", order_by="updated_at", order_desc=False, limit=limit)
    excluded_statuses = {"converted", "lost", "closed", "archived", "deleted"}
    return [
        {
            "id": row.get("id"),
            "name": row.get("name"),
            "company": row.get("company"),
            "email": row.get("email"),
            "phone": row.get("phone"),
            "status": row.get("status"),
            "source": row.get("source"),
            "owner_id": row.get("owner_id"),
            "organization_id": row.get("organization_id"),
            "updated_at": row.get("updated_at"),
            "created_at": row.get("created_at"),
            "last_contacted_at": row.get("last_contacted_at"),
            "score": row.get("score"),
            "score_reason": row.get("score_reason"),
        }
        for row in rows
        if row.get("id") and str(row.get("status") or "").strip().lower() not in excluded_statuses
    ]


@router.get("/deals/risk-candidates", status_code=status.HTTP_200_OK)
async def ai_service_deal_risk_candidates(
    limit: int = Query(default=500, ge=1, le=1000),
    _ai_agent: dict = Depends(require_ai_agent_auth),
    db: Client = Depends(get_db),
):
    """Return deal rows the AI service can evaluate for risk alerts."""
    rows = await _safe_table_select(db, "deals", order_by="updated_at", order_desc=False, limit=limit)
    excluded_stages = {"won", "lost", "closed", "archived", "deleted"}
    return [
        {
            "id": row.get("id"),
            "title": row.get("title"),
            "stage": row.get("stage"),
            "value": row.get("value"),
            "currency": row.get("currency"),
            "owner_id": row.get("owner_id"),
            "lead_id": row.get("lead_id"),
            "organization_id": row.get("organization_id"),
            "customer_id": row.get("customer_id"),
            "expected_close_at": row.get("expected_close_at"),
            "deal_type": row.get("deal_type"),
            "updated_at": row.get("updated_at"),
            "created_at": row.get("created_at"),
            "loss_reason": row.get("loss_reason"),
            "lost_reason": row.get("lost_reason"),
        }
        for row in rows
        if row.get("id") and str(row.get("stage") or "").strip().lower() not in excluded_stages
    ]


@router.get("/users/{user_id}/summary-context", status_code=status.HTTP_200_OK)
async def ai_service_user_summary_context(
    user_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    _ai_agent: dict = Depends(require_ai_agent_auth),
    db: Client = Depends(get_db),
):
    """Return role-scoped lead/deal/task context for a user's daily summary.

    Scope by the recipient's role:
    - admin: global (no owner filter)
    - sales_manager: records owned/assigned to their team members
    - sales_rep (default): records they own/are assigned
    """
    owner_id = str(user_id)

    def _query() -> dict[str, object]:
        with db.engine.connect() as conn:
            role = str(
                conn.execute(
                    text("SELECT role FROM agents WHERE id = :id"), {"id": owner_id}
                ).scalar()
                or ""
            ).strip().lower()

            # Scope clause per role. team_members/teams pattern reused from
            # admin_overview_service. {alias} is the owner/assignee column expr.
            if role == "admin":
                scope_type = "global"

                def scope(_alias: str) -> str:
                    return ""
            elif role in {"sales_manager", "manager"}:
                scope_type = "team"

                def scope(alias: str) -> str:
                    # team members' records OR the manager's own
                    return (
                        f" AND ({alias} = :owner_id OR EXISTS ("
                        "SELECT 1 FROM team_members tm JOIN teams team_scope ON team_scope.id = tm.team_id "
                        f"WHERE team_scope.manager_id = :owner_id AND tm.agent_id = {alias})) "
                    )
            else:
                scope_type = "owned"

                def scope(alias: str) -> str:
                    return f" AND {alias} = :owner_id "

            params = {"owner_id": owner_id, "limit": limit}

            leads = conn.execute(
                text(
                    "SELECT id::text, name, company, email, status, source, owner_id::text, "
                    "organization_id::text, score, score_reason, updated_at, created_at "
                    f"FROM leads WHERE 1=1 {scope('owner_id')} "
                    "ORDER BY updated_at DESC LIMIT :limit"
                ),
                params,
            ).mappings().all()
            deals = conn.execute(
                text(
                    "SELECT d.id::text, d.title, d.stage, d.value, d.currency, d.owner_id::text, "
                    "d.lead_id::text, d.organization_id::text, d.customer_id::text, "
                    "d.expected_close_at, d.deal_type, d.updated_at, d.created_at "
                    "FROM deals d LEFT JOIN leads l ON l.id = d.lead_id "
                    f"WHERE 1=1 {scope('COALESCE(d.owner_id, l.owner_id)')} "
                    "ORDER BY d.updated_at DESC LIMIT :limit"
                ),
                params,
            ).mappings().all()
            tasks = conn.execute(
                text(
                    "SELECT id::text, title, status, priority, due_at, assigned_to::text, "
                    "entity_type, entity_id::text, updated_at "
                    f"FROM tasks t WHERE 1=1 {scope('assigned_to')} "
                    "ORDER BY (due_at IS NULL), due_at ASC, updated_at DESC LIMIT :limit"
                ),
                params,
            ).mappings().all()
            return {
                "scope": scope_type,
                "owned_leads": [dict(row) for row in leads],
                "owned_deals": [dict(row) for row in deals],
                "tasks": [dict(row) for row in tasks],
            }

    try:
        return await run_db_operation(_query)
    except Exception:
        # Fallback: owned-only via the safe table select (no scope escalation).
        leads = await _safe_table_select(db, "leads", filters={"owner_id": owner_id}, order_by="updated_at", order_desc=True, limit=limit)
        deals = await _safe_table_select(db, "deals", filters={"owner_id": owner_id}, order_by="updated_at", order_desc=True, limit=limit)
        return {"scope": "owned", "owned_leads": list(leads), "owned_deals": list(deals), "tasks": []}


@router.get("/rag/snapshot", status_code=status.HTTP_200_OK)
async def ai_service_rag_snapshot(
    entity_type: str | None = None,
    changed_since: str | None = None,
    limit: int = 100,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    db: Client = Depends(get_db),
):
    """
    Return CRM text documents for AI-service RAG indexing.

    The worker calls this in small background batches. The backend remains the
    source of truth and only emits normalized, indexable documents.
    """
    batch_limit = min(max(limit, 1), 250)
    allowed_types = {"lead", "deal", "task", "note", "call", "agent", "user", "organization", "customer"}
    if entity_type and entity_type not in allowed_types:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported entity_type")

    def _query() -> list[dict]:
        clauses = []
        params: dict[str, object] = {"limit": batch_limit}
        if changed_since:
            params["changed_since"] = changed_since

        def maybe_filter(updated_expr: str) -> str:
            filters = []
            if changed_since:
                filters.append(f"{updated_expr} >= CAST(:changed_since AS timestamptz)")
            return "WHERE " + " AND ".join(filters) if filters else ""

        if entity_type in {None, "lead"}:
            clauses.append(
            f"""
            SELECT 'lead' AS kind, 'lead' AS target_entity_type, leads.id::text AS entity_id, leads.id::text AS source_id,
                   leads.owner_id::text AS owner_id, leads.updated_at, concat_ws(' ',
                       'Lead',
                       to_jsonb(leads)->>'name',
                       to_jsonb(leads)->>'email',
                       to_jsonb(leads)->>'phone',
                       to_jsonb(leads)->>'company',
                       to_jsonb(leads)->>'source',
                       to_jsonb(leads)->>'status',
                       'Organization',
                       to_jsonb(organizations)->>'name',
                       to_jsonb(organizations)->>'industry',
                       to_jsonb(leads)->>'lost_reason',
                       to_jsonb(leads)->>'lost_notes',
                       to_jsonb(leads)->>'score_reason',
                       to_jsonb(leads)->>'notes'
                   ) AS content
            FROM leads
            LEFT JOIN organizations ON organizations.id = leads.organization_id
            {maybe_filter('leads.updated_at')}
            """
            )
        if entity_type in {None, "organization"}:
            clauses.append(
            f"""
            SELECT 'organization' AS kind, 'organization' AS target_entity_type, id::text AS entity_id, id::text AS source_id,
                   owner_id::text AS owner_id, updated_at, concat_ws(' ',
                       'Organization',
                       to_jsonb(organizations)->>'name',
                       to_jsonb(organizations)->>'website',
                       to_jsonb(organizations)->>'industry',
                       to_jsonb(organizations)->>'revenue',
                       to_jsonb(organizations)->>'address',
                       to_jsonb(organizations)->>'phone'
                   ) AS content
            FROM organizations
            {maybe_filter('updated_at')}
            """
            )
        if entity_type in {None, "customer"}:
            clauses.append(
            f"""
            SELECT 'customer' AS kind, 'customer' AS target_entity_type, id::text AS entity_id, id::text AS source_id,
                   owner_id::text AS owner_id, updated_at, concat_ws(' ',
                       'Customer',
                       to_jsonb(customers)->>'full_name',
                       to_jsonb(customers)->>'email',
                       to_jsonb(customers)->>'phone',
                       to_jsonb(customers)->>'company',
                       to_jsonb(customers)->>'status',
                       to_jsonb(customers)->>'notes',
                       to_jsonb(customers)->>'metadata'
                   ) AS content
            FROM customers
            {maybe_filter('updated_at')}
            """
            )
        if entity_type in {None, "deal"}:
            clauses.append(
            f"""
            SELECT 'deal' AS kind, 'deal' AS target_entity_type, deals.id::text AS entity_id, deals.id::text AS source_id,
                   deals.owner_id::text AS owner_id, deals.updated_at, concat_ws(' ',
                       'Deal',
                       to_jsonb(deals)->>'title',
                       to_jsonb(deals)->>'stage',
                       to_jsonb(deals)->>'value',
                       to_jsonb(deals)->>'currency',
                       to_jsonb(deals)->>'expected_close_at',
                       to_jsonb(deals)->>'deal_type',
                       'Lead',
                       to_jsonb(leads)->>'name',
                       'Organization',
                       to_jsonb(organizations)->>'name',
                       'Customer',
                       to_jsonb(customers)->>'full_name',
                       to_jsonb(customers)->>'company',
                       to_jsonb(deals)->>'lost_reason',
                       to_jsonb(deals)->>'loss_reason'
                   ) AS content
            FROM deals
            LEFT JOIN leads ON leads.id = deals.lead_id
            LEFT JOIN organizations ON organizations.id = deals.organization_id
            LEFT JOIN customers ON customers.id = deals.customer_id
            {maybe_filter('deals.updated_at')}
            """
            )
        if entity_type in {None, "task"}:
            clauses.append(
            f"""
            SELECT 'task' AS kind, entity_type AS target_entity_type, entity_id::text AS entity_id, id::text AS source_id,
                   assigned_to::text AS owner_id, updated_at, concat_ws(' ',
                       'Task',
                       to_jsonb(tasks)->>'title',
                       to_jsonb(tasks)->>'description',
                       to_jsonb(tasks)->>'status',
                       to_jsonb(tasks)->>'priority',
                       to_jsonb(tasks)->>'due_at',
                       to_jsonb(tasks)->>'source',
                       to_jsonb(tasks)->>'ai_reason'
                   ) AS content
            FROM tasks
            {maybe_filter('updated_at')}
              {"AND" if changed_since else "WHERE"} entity_id IS NOT NULL
            """
            )
        if entity_type in {None, "note"}:
            clauses.append(
            f"""
            SELECT 'note' AS kind, entity_type AS target_entity_type, entity_id::text AS entity_id, id::text AS source_id,
                   author_id::text AS owner_id, updated_at, concat_ws(' ',
                       'Note',
                       to_jsonb(notes)->>'content',
                       to_jsonb(notes)->>'source',
                       to_jsonb(notes)->>'ai_reason'
                   ) AS content
            FROM notes
            {maybe_filter('updated_at')}
              {"AND" if changed_since else "WHERE"} entity_id IS NOT NULL
            """
            )
        if entity_type in {None, "call"}:
            clauses.append(
            f"""
            SELECT 'call' AS kind, 'lead' AS target_entity_type, lead_id::text AS entity_id, id::text AS source_id,
                   initiated_by::text AS owner_id, updated_at, concat_ws(' ',
                       'Call',
                       to_jsonb(call_sessions)->>'status',
                       to_jsonb(call_sessions)->>'direction',
                       to_jsonb(call_sessions)->>'started_at',
                       to_jsonb(call_sessions)->>'ended_at',
                       to_jsonb(call_sessions)->>'transcript',
                       to_jsonb(call_sessions)->>'meeting_summary'
                   ) AS content
            FROM call_sessions
            {maybe_filter('updated_at')}
              {"AND" if changed_since else "WHERE"} lead_id IS NOT NULL
            """
            )
        if entity_type in {None, "agent", "user"}:
            clauses.append(
            f"""
            SELECT 'agent' AS kind, 'user' AS target_entity_type, id::text AS entity_id, id::text AS source_id,
                   id::text AS owner_id, updated_at, concat_ws(' ',
                       'Agent',
                       to_jsonb(agents)->>'full_name',
                       to_jsonb(agents)->>'name',
                       to_jsonb(agents)->>'email',
                       to_jsonb(agents)->>'role'
                   ) AS content
            FROM agents
            {maybe_filter('updated_at')}
            """
            )
        sql = " UNION ALL ".join(clauses) + " ORDER BY updated_at ASC LIMIT :limit"
        with db.engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
            return [dict(row) for row in rows]

    rows = await run_db_operation(_query)
    documents = [
        {
            "entity_type": row["target_entity_type"],
            "entity_id": row["entity_id"],
            "source": f"backend.{row['kind']}",
            "source_id": row["source_id"],
            "content": str(row.get("content") or "").strip(),
            "updated_at": row["updated_at"].isoformat() if hasattr(row.get("updated_at"), "isoformat") else row.get("updated_at"),
            "metadata": {
                "source_table": row["kind"],
                "source_id": row["source_id"],
                "owner_id": row.get("owner_id"),
                "entity_type": row["target_entity_type"],
                "entity_id": row["entity_id"],
            },
        }
        for row in rows
        if str(row.get("content") or "").strip()
    ]
    return {"documents": documents, "count": len(documents)}


@router.post("/rag/reconcile", status_code=status.HTTP_200_OK)
async def ai_service_rag_reconcile(
    payload: dict,
    _current_user: dict = Depends(require_human_or_ai_agent_auth),
    db: Client = Depends(get_db),
):
    """
    Return which indexed backend source records no longer exist.

    This lets the AI worker remove stale FAISS chunks even when the source row
    was hard-deleted and therefore cannot appear in an incremental snapshot.
    """
    raw_sources = payload.get("sources") if isinstance(payload, dict) else []
    if not isinstance(raw_sources, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sources must be a list")

    table_by_source = {
        "lead": "leads",
        "deal": "deals",
        "task": "tasks",
        "note": "notes",
        "call": "call_sessions",
        "agent": "agents",
        "user": "agents",
        "organization": "organizations",
        "customer": "customers",
    }
    normalized = []
    for item in raw_sources[:1000]:
        if not isinstance(item, dict):
            continue
        source_table = str(item.get("source_table") or "").strip()
        source_id = str(item.get("source_id") or "").strip()
        if source_table in table_by_source and source_id:
            normalized.append({"source_table": source_table, "source_id": source_id})

    def _query_existing() -> set[tuple[str, str]]:
        existing: set[tuple[str, str]] = set()
        with db.engine.connect() as conn:
            for source_table, table_name in table_by_source.items():
                ids = [item["source_id"] for item in normalized if item["source_table"] == source_table]
                if not ids:
                    continue
                rows = conn.execute(
                    text(f"SELECT id::text AS id FROM {table_name} WHERE id::text = ANY(:ids)"),
                    {"ids": ids},
                ).mappings().all()
                existing.update((source_table, str(row["id"])) for row in rows)
        return existing

    existing = await run_db_operation(_query_existing)
    missing = [item for item in normalized if (item["source_table"], item["source_id"]) not in existing]
    return {"missing": missing, "checked": len(normalized)}
