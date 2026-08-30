"""Internal frontdesk contracts for the AI service.

The AI service owns conversation intelligence but never writes to the database
directly. It calls these endpoints with its service token; the backend validates
payloads, enforces ownership/assignment rules, guarantees idempotency, and
performs every CRM write.

Auth: X-AI-Service-Token (require_ai_agent_auth) - no human cookie access.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text

from app.auth.dependencies import require_ai_agent_auth
from app.config import settings
from app.database import get_db, run_db_operation
from app.postgres_client import PostgresClient
from app.schemas.frontdesk import (
    InternalAppointmentCreate,
    InternalHandoffCreate,
    InternalLeadUpsert,
    InternalNoteCreate,
    InternalStateUpdate,
    InternalTaskCreate,
)
from app.services import calcom
from app.services.notification_service import NotificationService

router = APIRouter(dependencies=[Depends(require_ai_agent_auth)])

logger = logging.getLogger(__name__)

MAX_STATE_BYTES = 32768

def _zone_ok(zone: str) -> bool:
    """Whether this zone name is usable, so a bad one only costs the pretty wording."""
    try:
        ZoneInfo(zone)
        return True
    except Exception:
        return False

async def query(db: PostgresClient, sql: str, params: dict | None = None, many: bool = False):
    def execute():
        with db.engine.begin() as conn:
            result = conn.execute(text(sql), params or {})
            if not result.returns_rows:
                return None
            if many:
                return [dict(row) for row in result.mappings().all()]
            row = result.mappings().first()
            return dict(row) if row else None
    return await run_db_operation(execute)

DDL_STATEMENTS = [
    # Base tables (idempotent).
    """CREATE TABLE IF NOT EXISTS frontdesk_sessions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        channel VARCHAR(30) NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'active',
        contact_type VARCHAR(30),
        contact_id UUID,
        contact_name VARCHAR(255),
        contact_email VARCHAR(255),
        lead_owner_id UUID,
        intent VARCHAR(80),
        urgency VARCHAR(20),
        handoff_reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS frontdesk_messages (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        session_id UUID NOT NULL REFERENCES frontdesk_sessions(id) ON DELETE CASCADE,
        direction VARCHAR(20) NOT NULL,
        sender_type VARCHAR(30) NOT NULL,
        content TEXT NOT NULL,
        provider_message_id VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS frontdesk_appointments (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        session_id UUID NOT NULL REFERENCES frontdesk_sessions(id) ON DELETE CASCADE,
        lead_id UUID,
        owner_id UUID,
        title VARCHAR(255) NOT NULL,
        notes TEXT,
        starts_at TIMESTAMPTZ NOT NULL,
        ends_at TIMESTAMPTZ NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'confirmed',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    # Runtime-state columns (mirrors migrations 013/014, safe to re-run).
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS mode VARCHAR(30) NOT NULL DEFAULT 'frontdesk'""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS discovery_stage VARCHAR(40) NOT NULL DEFAULT 'greeting'""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS identity_status VARCHAR(30) NOT NULL DEFAULT 'unknown'""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS identity_confidence NUMERIC(5,4)""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS handoff_status VARCHAR(30)""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS handoff_summary TEXT""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS summary TEXT""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS discovery_facts JSONB NOT NULL DEFAULT '{}'::jsonb""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS ai_state JSONB NOT NULL DEFAULT '{}'::jsonb""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS visitor_token_hash VARCHAR(255)""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS consent_accepted_at TIMESTAMPTZ""",
    # handoff_assigned_to shipped in migration 014 but was missing here, so a DB
    # bootstrapped by ensure_tables alone failed every handoff and takeover.
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS handoff_assigned_to UUID REFERENCES agents(id) ON DELETE SET NULL""",
    # The handoff grace period: while this is in the future a rep can still join
    # and answer live, so the visitor is not emailed "we'll get back to you".
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS handoff_wait_until TIMESTAMPTZ""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS handoff_notified_at TIMESTAMPTZ""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ""",
    """ALTER TABLE frontdesk_sessions ADD COLUMN IF NOT EXISTS closed_by UUID REFERENCES agents(id) ON DELETE SET NULL""",
    """ALTER TABLE frontdesk_appointments ADD COLUMN IF NOT EXISTS provider VARCHAR(30) NOT NULL DEFAULT 'cal.com'""",
    """ALTER TABLE frontdesk_appointments ADD COLUMN IF NOT EXISTS provider_uid VARCHAR(255)""",
    """ALTER TABLE frontdesk_appointments ADD COLUMN IF NOT EXISTS meeting_url TEXT""",
    """ALTER TABLE frontdesk_appointments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()""",
    """CREATE TABLE IF NOT EXISTS frontdesk_handoffs (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        session_id UUID NOT NULL REFERENCES frontdesk_sessions(id) ON DELETE CASCADE,
        reason TEXT NOT NULL,
        summary TEXT,
        urgency VARCHAR(20) NOT NULL DEFAULT 'normal',
        assigned_to UUID REFERENCES agents(id) ON DELETE SET NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'open',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        resolved_at TIMESTAMPTZ
    )""",
    """ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'manual'""",
    """ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ai_reason TEXT""",
    """ALTER TABLE notes ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'manual'""",
    """ALTER TABLE notes ADD COLUMN IF NOT EXISTS ai_reason TEXT""",
    "CREATE INDEX IF NOT EXISTS idx_frontdesk_messages_session ON frontdesk_messages(session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_frontdesk_handoffs_session ON frontdesk_handoffs(session_id, created_at DESC)",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_frontdesk_appointments_provider_uid
       ON frontdesk_appointments(provider, provider_uid) WHERE provider_uid IS NOT NULL""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_frontdesk_sessions_visitor_token
       ON frontdesk_sessions(visitor_token_hash) WHERE visitor_token_hash IS NOT NULL""",
]

_tables_ready = False
# Without this, concurrent first requests each start a full DDL pass and then
# serialize behind each other's ACCESS EXCLUSIVE locks, blowing request timeouts.
_tables_lock = asyncio.Lock()

async def ensure_tables(db: PostgresClient) -> None:
    global _tables_ready
    if _tables_ready:
        return
    async with _tables_lock:
        if _tables_ready:
            return

        # One transaction, one round trip: 30 separate round trips to a hosted
        # Postgres was slow enough to time out the first page load.
        def execute():
            with db.engine.begin() as conn:
                for statement in DDL_STATEMENTS:
                    conn.execute(text(statement))

        await run_db_operation(execute)
        _tables_ready = True

def new_visitor_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()

async def require_session(db: PostgresClient, session_id: UUID) -> dict:
    session = await query(db, "SELECT * FROM frontdesk_sessions WHERE id=:id", {"id": str(session_id)})
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Front-desk session not found")
    return session

async def validated_assignee(db: PostgresClient, suggested_id: UUID | None) -> UUID | None:
    """The model may recommend an assignee; only the backend decides if it is allowed."""
    if suggested_id:
        agent = await query(
            db,
            "SELECT id FROM agents WHERE id=:id AND is_active=true AND status='active'",
            {"id": str(suggested_id)},
        )
        if agent:
            return UUID(str(agent["id"]))
    return None

async def fallback_owner(db: PostgresClient) -> UUID | None:
    """Routing fallback for new leads: an active admin, then manager, then rep."""
    for role in ("admin", "sales_manager", "sales_rep"):
        agent = await query(
            db,
            "SELECT id FROM agents WHERE role=:role AND is_active=true AND status='active' ORDER BY created_at LIMIT 1",
            {"role": role},
        )
        if agent:
            return UUID(str(agent["id"]))
    return None

async def notify_owner(
    db: PostgresClient,
    *,
    recipient_id: str | UUID | None,
    type: str,
    title: str,
    message: str,
    entity_type: str,
    entity_id: str | UUID | None,
) -> None:
    """Tell a CRM user about something the front desk did on their behalf.

    `actor_id` is None because the front-desk agent is not an agents row; that
    is the same convention the deadline service uses for system notifications.
    A notification is a courtesy, never a reason to fail the CRM write, so
    every failure here is swallowed.
    """
    if not recipient_id:
        return
    try:
        await NotificationService(db).create_notification(
            recipient_id=str(recipient_id),
            actor_id=None,
            type=type,
            title=title,
            message=message,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
        )
    except Exception:
        logger.warning("frontdesk_notification_failed type=%s entity=%s", type, entity_id, exc_info=True)

async def session_lead(db: PostgresClient, session: dict, lead_id: UUID | None) -> dict:
    """Resolve the CRM lead a write applies to; never trust a lead_id that is not linked.

    Selects name/email too: the calendar needs a real attendee, and a lead dict
    without them silently refused every booking.
    """
    if lead_id:
        lead = await query(db, "SELECT id, owner_id, name, email FROM leads WHERE id=:id", {"id": str(lead_id)})
        if not lead:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lead not found")
        if session.get("contact_id") and str(session["contact_id"]) != str(lead["id"]):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lead is not linked to this session")
        return lead
    if session.get("contact_type") == "lead" and session.get("contact_id"):
        lead = await query(db, "SELECT id, owner_id, name, email FROM leads WHERE id=:id", {"id": str(session["contact_id"])})
        if lead:
            return lead
        return {"id": session["contact_id"], "owner_id": session.get("lead_owner_id")}
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "No matched lead on this session; upsert the lead first")

# ---------------------------------------------------------------------------
# Session context + runtime state
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}")
async def get_session_context(session_id: UUID, db: PostgresClient = Depends(get_db)):
    """Full service view: session row (incl. ai_state) plus recent messages."""
    await ensure_tables(db)
    session = await require_session(db, session_id)
    messages = await query(
        db,
        "SELECT direction, sender_type, content, created_at FROM frontdesk_messages WHERE session_id=:id ORDER BY created_at DESC LIMIT 60",
        {"id": str(session_id)},
        many=True,
    )
    session["messages"] = list(reversed(messages or []))
    return session

@router.put("/sessions/{session_id}/state")
async def update_state(session_id: UUID, payload: InternalStateUpdate, db: PostgresClient = Depends(get_db)):
    await ensure_tables(db)
    await require_session(db, session_id)
    encoded = json.dumps(payload.state, ensure_ascii=False, default=str)
    if len(encoded.encode()) > MAX_STATE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Runtime state exceeds 32KB")
    row = await query(
        db,
        """UPDATE frontdesk_sessions
           SET ai_state=CAST(:state AS jsonb),
               discovery_stage=COALESCE(:stage, discovery_stage),
               summary=COALESCE(:summary, summary),
               discovery_facts=CASE WHEN :has_facts THEN discovery_facts || CAST(:facts AS jsonb) ELSE discovery_facts END,
               updated_at=NOW()
           WHERE id=:id RETURNING id, discovery_stage, summary""",
        {
            "id": str(session_id),
            "state": encoded,
            "stage": payload.stage,
            "summary": payload.summary,
            "facts": json.dumps(payload.facts, ensure_ascii=False, default=str) if payload.facts else None,
            "has_facts": bool(payload.facts),
        },
    )
    return {"ok": True, "session_id": str(session_id), "stage": row.get("discovery_stage") if row else None}

# ---------------------------------------------------------------------------
# Lead upsert (identity resolution)
# ---------------------------------------------------------------------------

@router.post("/leads/upsert")
async def upsert_lead(payload: InternalLeadUpsert, db: PostgresClient = Depends(get_db)):
    """Resolve a visitor against existing leads by exact email/phone, else create one.

    The AI service supplies the facts; the backend owns duplicate protection,
    owner routing, and the CRM record itself.
    """
    await ensure_tables(db)
    session = await require_session(db, payload.session_id)

    lead = None
    matched_by = None
    if payload.email:
        lead = await query(
            db,
            "SELECT id, name, email, company, owner_id FROM leads WHERE lower(email)=lower(:email) LIMIT 1",
            {"email": payload.email.strip()},
        )
        matched_by = "email"
    if not lead and payload.phone:
        digits = "".join(ch for ch in payload.phone if ch.isdigit())
        lead = await query(
            db,
            "SELECT id, name, email, company, owner_id FROM leads WHERE regexp_replace(phone,'[^0-9]','','g')=:digits LIMIT 1",
            {"digits": digits},
        )
        matched_by = "phone"

    created = False
    if lead:
        updates, params = [], {"id": str(lead["id"])}
        if payload.company and not lead.get("company"):
            updates.append("company=:company"); params["company"] = payload.company
        if payload.name and not lead.get("name"):
            updates.append("name=:name"); params["name"] = payload.name
        if updates:
            await query(db, f"UPDATE leads SET {', '.join(updates)}, updated_at=NOW() WHERE id=:id", params)
        owner_id = lead.get("owner_id")
    else:
        owner_id = await validated_assignee(db, payload.suggested_owner_id) or await fallback_owner(db)
        lead = await query(
            db,
            """INSERT INTO leads (name, email, phone, company, source, status, owner_id)
               VALUES (:name, :email, :phone, :company, :source, 'new', :owner) RETURNING id, name, email, company, owner_id""",
            {
                "name": payload.name,
                "email": payload.email,
                "phone": payload.phone,
                "company": payload.company,
                "source": payload.source or "frontdesk_chat",
                "owner": str(owner_id) if owner_id else None,
            },
        )
        created = True
        matched_by = None

    session_row = await query(
        db,
        """UPDATE frontdesk_sessions
           SET contact_type='lead', contact_id=:cid, contact_name=COALESCE(:name, contact_name),
               contact_email=COALESCE(:email, contact_email), lead_owner_id=:owner,
               identity_status=CASE WHEN :matched THEN 'matched' ELSE 'created' END,
               identity_confidence=CASE WHEN :matched THEN 1 ELSE 0 END,
               updated_at=NOW()
           WHERE id=:id RETURNING id, contact_id, lead_owner_id, identity_status""",
        {
            "id": str(payload.session_id),
            "cid": str(lead["id"]),
            "name": lead.get("name"),
            "email": lead.get("email"),
            "owner": str(lead["owner_id"]) if lead.get("owner_id") else None,
            "matched": bool(matched_by),
        },
    )
    return {
        "lead_id": str(lead["id"]),
        "owner_id": str(lead["owner_id"]) if lead.get("owner_id") else None,
        "identity_status": "matched" if matched_by else "created",
        "matched_by": matched_by,
        "created": created,
        "session": session_row,
    }

# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------

@router.post("/handoffs")
async def create_handoff(payload: InternalHandoffCreate, db: PostgresClient = Depends(get_db)):
    await ensure_tables(db)
    session = await require_session(db, payload.session_id)

    existing = await query(
        db,
        "SELECT * FROM frontdesk_handoffs WHERE session_id=:sid AND status='open' ORDER BY created_at DESC LIMIT 1",
        {"sid": str(payload.session_id)},
    )
    if existing:
        # Re-asking does not restart the clock; report the window already running
        # so the agent's wording stays consistent with the first request.
        return {"handoff_id": str(existing["id"]), "status": "open", "duplicate": True,
                "assigned_to": existing.get("assigned_to"),
                "wait_until": session["handoff_wait_until"].isoformat() if session.get("handoff_wait_until") else None,
                "wait_minutes": settings.FRONTDESK_HANDOFF_WAIT_MINUTES}

    assignee = await validated_assignee(db, payload.suggested_assignee_id)
    if not assignee and session.get("lead_owner_id"):
        assignee = await validated_assignee(db, UUID(str(session["lead_owner_id"])))
    handoff = await query(
        db,
        """INSERT INTO frontdesk_handoffs (session_id, reason, summary, urgency, assigned_to)
           VALUES (:sid, :reason, :summary, :urgency, :assignee) RETURNING id, status, assigned_to""",
        {
            "sid": str(payload.session_id),
            "reason": payload.reason,
            "summary": payload.summary,
            "urgency": payload.urgency,
            "assignee": str(assignee) if assignee else None,
        },
    )
    # The grace period starts now: while it runs the visitor is asked to hold,
    # because a rep joining in time answers live and no email is needed.
    wait_until = datetime.now(timezone.utc) + timedelta(minutes=settings.FRONTDESK_HANDOFF_WAIT_MINUTES)
    await query(
        db,
        """UPDATE frontdesk_sessions SET status='waiting_human', mode='human_handoff',
           handoff_status='open', handoff_reason=:reason, handoff_summary=COALESCE(:summary, handoff_summary),
           handoff_assigned_to=COALESCE(:assignee, handoff_assigned_to),
           handoff_wait_until=:wait, handoff_notified_at=NULL,
           intent=COALESCE(:intent, intent), urgency=:urgency, updated_at=NOW() WHERE id=:id""",
        {
            "id": str(payload.session_id),
            "reason": payload.reason,
            "summary": payload.summary,
            "assignee": str(assignee) if assignee else None,
            "wait": wait_until,
            "intent": payload.intent,
            "urgency": payload.urgency,
        },
    )
    # Whoever is expected to answer needs to know a visitor is waiting right now.
    await notify_owner(
        db,
        recipient_id=assignee,
        type="frontdesk_handoff",
        title="A visitor is waiting to speak with you",
        message=f"{session.get('contact_name') or 'A visitor'} asked for a human: {payload.reason}. "
                f"Join the chat within {settings.FRONTDESK_HANDOFF_WAIT_MINUTES} minutes to answer live.",
        entity_type="lead" if session.get("contact_type") == "lead" else "frontdesk_session",
        entity_id=session.get("contact_id") if session.get("contact_type") == "lead" else payload.session_id,
    )
    return {"handoff_id": str(handoff["id"]), "status": handoff.get("status", "open"), "duplicate": False,
            "assigned_to": handoff.get("assigned_to"),
            "wait_until": wait_until.isoformat(),
            "wait_minutes": settings.FRONTDESK_HANDOFF_WAIT_MINUTES}

# ---------------------------------------------------------------------------
# Appointments (booking) + the single owner task
# ---------------------------------------------------------------------------

@router.get("/slots")
async def list_slots(day: datetime, time_zone: str | None = None):
    """Bookable openings on the business-local day containing `day`.

    The agent offers these verbatim and books the exact string the visitor
    picks, so a guessed timestamp can never land outside availability.
    """
    zone = time_zone or calcom.business_timezone()
    return {
        "time_zone": zone,
        "slots": await calcom.available_slots(day=day, time_zone=zone),
        "configured": calcom.is_configured(),
    }

@router.post("/appointments")
async def create_appointment(payload: InternalAppointmentCreate, db: PostgresClient = Depends(get_db)):
    await ensure_tables(db)
    session = await require_session(db, payload.session_id)
    lead = await session_lead(db, session, payload.lead_id)

    if payload.meeting.ends_at <= payload.meeting.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Meeting end must be after its start")

    # A bare clock time from the visitor means the business zone, not UTC, and
    # the CRM row must record the same instant the calendar holds.
    zone = payload.meeting.time_zone or calcom.business_timezone()
    payload.meeting.starts_at = calcom.localize(payload.meeting.starts_at, zone)
    payload.meeting.ends_at = calcom.localize(payload.meeting.ends_at, zone)

    provider_uid = payload.meeting.uid or f"session:{payload.session_id}:{payload.meeting.starts_at.isoformat()}"
    # Replay guard is provider-independent: the same session cannot hold two
    # appointments for the same slot, whichever calendar backed them.
    existing = await query(
        db,
        "SELECT * FROM frontdesk_appointments WHERE session_id=:sid AND starts_at=:starts LIMIT 1",
        {"sid": str(payload.session_id), "starts": payload.meeting.starts_at},
    )
    if existing:
        if existing.get("provider") == "cal.com":
            return {"appointment": existing, "task_id": None, "assignee_id": existing.get("owner_id"),
                    "duplicate": True, "calendar_synced": True, "calendar_error": None,
                    "alternative_slots": []}
        # The earlier attempt never reached the calendar, so it is a failed
        # request, not a booking. Drop it and try the calendar again; otherwise
        # the visitor picking the same slot twice can never succeed.
        await query(db, "DELETE FROM frontdesk_appointments WHERE id=:id", {"id": str(existing["id"])})

    # Place the booking on the real calendar. A Cal.com failure does not lose
    # the request: it is still recorded and the caller is told the calendar
    # invite is missing so the visitor is not promised an invitation.
    provider, meeting_url, calendar_error = payload.meeting.provider, payload.meeting.meeting_url, None
    alternative_slots: list[str] = []
    if calcom.is_configured():
        booking = await calcom.create_booking(
            starts_at=payload.meeting.starts_at,
            attendee_name=str(lead.get("name") or ""),
            attendee_email=str(lead.get("email") or ""),
            time_zone=zone,
            notes=payload.summary,
        )
        if booking.get("error"):
            calendar_error = booking["error"]
            alternative_slots = booking.get("alternative_slots") or []
        else:
            provider = "cal.com"
            provider_uid = booking.get("uid") or provider_uid
            meeting_url = booking.get("meeting_url") or meeting_url
    else:
        calendar_error = "Cal.com is not configured"
    # When the slot is refused, hand back real openings that day so the agent can
    # offer a time the calendar will actually accept instead of guessing again.
    if calendar_error:
        logger.warning(
            "frontdesk_calendar_not_synced session=%s starts_at=%s: %s",
            payload.session_id, payload.meeting.starts_at, calendar_error,
        )
        if not alternative_slots and calcom.is_configured():
            alternative_slots = (await calcom.available_slots(
                day=payload.meeting.starts_at, time_zone=zone))[:6]

    # Permitted owner: validated suggestion -> lead owner -> routing fallback.
    owner_id = await validated_assignee(db, payload.suggested_assignee_id)
    if not owner_id and lead.get("owner_id"):
        owner_id = await validated_assignee(db, UUID(str(lead["owner_id"])))
    if not owner_id:
        owner_id = await fallback_owner(db)

    appointment = await query(
        db,
        """INSERT INTO frontdesk_appointments
           (session_id, lead_id, owner_id, title, notes, starts_at, ends_at, provider, provider_uid, meeting_url)
           VALUES (:sid, :lead, :owner, :title, :notes, :starts, :ends, :provider, :uid, :url) RETURNING *""",
        {
            "sid": str(payload.session_id),
            "lead": str(lead["id"]),
            "owner": str(owner_id) if owner_id else None,
            "title": payload.meeting.title,
            "notes": payload.summary,
            "starts": payload.meeting.starts_at,
            "ends": payload.meeting.ends_at,
            "provider": provider,
            "uid": provider_uid,
            "url": meeting_url,
        },
    )

    # Exactly one preparation task per booking. The owner always gets one, even
    # when the agent forgot to request it: a meeting nobody is told to prepare
    # for is the failure mode this is here to prevent.
    requested = payload.requested_task
    task_title = requested.title if requested else f"Prepare for {payload.meeting.title}"
    task_id = None
    duplicate = await query(
        db,
        "SELECT id FROM tasks WHERE entity_type='lead' AND entity_id=:lead AND source='frontdesk' AND title=:title LIMIT 1",
        {"lead": str(lead["id"]), "title": task_title},
    )
    if not duplicate:
        task = await query(
            db,
            """INSERT INTO tasks (entity_type, entity_id, title, description, assigned_to, status, priority, due_at, source, ai_reason)
               VALUES ('lead', :lead, :title, :description, :assignee, 'backlog', :priority, :due, 'frontdesk', :reason) RETURNING id""",
            {
                "lead": str(lead["id"]),
                "title": task_title,
                "description": (requested.description if requested else None) or payload.summary
                               or f"Meeting booked by the front desk for {lead.get('name') or 'this lead'}.",
                "assignee": str(owner_id) if owner_id else None,
                "priority": requested.priority if requested else "medium",
                "due": (requested.due_at if requested else None) or payload.meeting.starts_at,
                "reason": f"Created by front-desk booking (appointment {appointment['id']})",
            },
        )
        task_id = str(task["id"]) if task else None
    else:
        task_id = str(duplicate["id"])

    # The owner learns about a meeting on their calendar from the CRM, not from
    # discovering it later.
    when = payload.meeting.starts_at.astimezone(ZoneInfo(zone)) if _zone_ok(zone) else payload.meeting.starts_at
    await notify_owner(
        db,
        recipient_id=owner_id,
        type="frontdesk_meeting_booked",
        title="Meeting booked by the front desk",
        message=f"{lead.get('name') or 'A lead'} booked {payload.meeting.title} for "
                f"{when.strftime('%a %d %b %Y at %I:%M %p')} ({zone})."
                + ("" if calendar_error is None else " The calendar invite could not be sent."),
        entity_type="lead",
        entity_id=lead["id"],
    )

    if payload.summary:
        await query(
            db,
            "INSERT INTO notes (entity_type, entity_id, content, source, ai_reason) VALUES ('lead', :lead, :content, 'frontdesk', :reason)",
            {"lead": str(lead["id"]), "content": payload.summary, "reason": "Front-desk booking summary"},
        )

    return {
        "appointment": appointment,
        "task_id": task_id,
        "assignee_id": str(owner_id) if owner_id else None,
        "duplicate": False,
        "calendar_synced": calendar_error is None,
        "calendar_error": calendar_error,
        "alternative_slots": alternative_slots,
    }

# ---------------------------------------------------------------------------
# Tasks and notes
# ---------------------------------------------------------------------------

@router.post("/tasks")
async def create_task(payload: InternalTaskCreate, db: PostgresClient = Depends(get_db)):
    await ensure_tables(db)
    session = await require_session(db, payload.session_id)
    lead = await session_lead(db, session, payload.lead_id)

    duplicate = await query(
        db,
        "SELECT id, assigned_to FROM tasks WHERE entity_type='lead' AND entity_id=:lead AND source='frontdesk' AND title=:title LIMIT 1",
        {"lead": str(lead["id"]), "title": payload.title},
    )
    if duplicate:
        return {"task_id": str(duplicate["id"]), "assignee_id": duplicate.get("assigned_to"), "duplicate": True}

    assignee = await validated_assignee(db, payload.suggested_assignee_id)
    if not assignee and lead.get("owner_id"):
        assignee = await validated_assignee(db, UUID(str(lead["owner_id"])))
    task = await query(
        db,
        """INSERT INTO tasks (entity_type, entity_id, title, description, assigned_to, status, priority, due_at, source, ai_reason)
           VALUES ('lead', :lead, :title, :description, :assignee, 'backlog', :priority, :due, 'frontdesk', :reason) RETURNING id, assigned_to""",
        {
            "lead": str(lead["id"]),
            "title": payload.title,
            "description": payload.description,
            "assignee": str(assignee) if assignee else None,
            "priority": payload.priority,
            "due": payload.due_at,
            "reason": f"Requested by front-desk session {payload.session_id}",
        },
    )
    return {"task_id": str(task["id"]), "assignee_id": task.get("assigned_to"), "duplicate": False}

@router.post("/notes")
async def create_note(payload: InternalNoteCreate, db: PostgresClient = Depends(get_db)):
    await ensure_tables(db)
    session = await require_session(db, payload.session_id)
    lead = await session_lead(db, session, payload.lead_id)
    note = await query(
        db,
        "INSERT INTO notes (entity_type, entity_id, content, source, ai_reason) VALUES ('lead', :lead, :content, 'frontdesk', :reason) RETURNING id",
        {"lead": str(lead["id"]), "content": payload.content, "reason": f"Front-desk session {payload.session_id}"},
    )
    return {"note_id": str(note["id"])}
