"""Front-desk conversation gateway.

The backend is the CRM authority: it persists every message, enforces
authorization, and owns all writes. Conversation intelligence lives in the AI
service; it is called for each visitor turn and executes its own validated CRM
operations through the internal service contracts in frontdesk_internal.py.

Surfaces:
- Employee workspace (cookie auth): review conversations, test the agent, take over.
- Customer chat (/public/*): token-authenticated visitor sessions, customer-safe
  message views only.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth.dependencies import require_auth
from app.config import settings
from app.database import get_db
from app.postgres_client import PostgresClient
from app.routers.frontdesk_internal import (
    ensure_tables,
    new_visitor_token,
    query,
)
from app.schemas.frontdesk import (
    FrontDeskBookingRequest,
    FrontDeskDiscoveryFactsRequest,
    FrontDeskHandoffRequest,
    FrontDeskIdentityRequest,
    FrontDeskMessageCreate,
    FrontDeskMessageResponse,
    FrontDeskSessionCreate,
    FrontDeskSessionDetail,
    FrontDeskSessionResponse,
    PublicSessionCreate,
    PublicSessionDetail,
    PublicSessionResponse,
)
from app.services.email_service import MailjetEmailService

router = APIRouter()

def get_email_service(db: PostgresClient = Depends(get_db)) -> MailjetEmailService:
    return MailjetEmailService(db)

class FrontDeskEmailWebhook(BaseModel):
    sender_email: str
    sender_name: str | None = None
    subject: str | None = None
    body: str
    message_id: str | None = None

def _ai_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.AI_SERVICE_WEBHOOK_TOKEN:
        headers["X-AutoCRM-AI-Webhook-Token"] = settings.AI_SERVICE_WEBHOOK_TOKEN
    return headers

_SESSION_SELECT = """SELECT s.*, COALESCE(NULLIF(a.full_name, ''), NULLIF(a.email, '')) AS lead_owner_name,
              l.name AS lead_name
       FROM frontdesk_sessions s
       LEFT JOIN agents a ON a.id = s.lead_owner_id
       LEFT JOIN leads l ON l.id = s.contact_id AND s.contact_type = 'lead'"""

async def _require_session(db: PostgresClient, session_id: UUID) -> dict:
    session = await query(db, f"{_SESSION_SELECT} WHERE s.id=:id", {"id": str(session_id)})
    if not session:
        raise HTTPException(404, "Front-desk session not found")
    return session

async def _require_visitor_session(db: PostgresClient, session_id: UUID, token: str | None) -> dict:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Visitor token is required")
    session = await _require_session(db, session_id)
    expected = session.get("visitor_token_hash")
    if not expected or not hashlib.sha256(token.encode()).hexdigest() == expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid visitor token")
    return session

async def _ai_history(db: PostgresClient, session_id: UUID, limit: int = 40) -> list[dict]:
    rows = await query(
        db,
        "SELECT direction, sender_type, content FROM frontdesk_messages WHERE session_id=:id ORDER BY created_at DESC LIMIT :lim",
        {"id": str(session_id), "lim": limit},
        many=True,
    )
    return list(reversed(rows or []))

async def _persist_message(db: PostgresClient, session_id: UUID, direction: str, sender_type: str, content: str) -> dict:
    return await query(
        db,
        "INSERT INTO frontdesk_messages(session_id,direction,sender_type,content) VALUES (:sid,:direction,:sender,:content) RETURNING *",
        {"sid": str(session_id), "direction": direction, "sender": sender_type, "content": content},
    )

async def _mark_agent_unavailable(db: PostgresClient, session_id: UUID) -> None:
    await query(
        db,
        "UPDATE frontdesk_sessions SET status='waiting_human', handoff_reason='Front-desk agent unavailable', updated_at=NOW() WHERE id=:id",
        {"id": str(session_id)},
    )

def _wait_elapsed(session: dict) -> bool:
    """Whether the handoff grace period has run out with nobody joining."""
    wait_until = session.get("handoff_wait_until")
    if not wait_until:
        return False
    if wait_until.tzinfo is None:
        wait_until = wait_until.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= wait_until

async def _email_visitor(
    db: PostgresClient,
    email_service: MailjetEmailService,
    session: dict,
    *,
    subject: str,
    body: str,
) -> bool:
    """Email the visitor once about their waiting conversation.

    `recipient_id=None` because a visitor is not a CRM user, so the employee
    email preferences do not apply. Delivery is best-effort: a chat must never
    fail because Mailjet did.
    """
    to = session.get("contact_email")
    if not to:
        return False
    try:
        await email_service.send_email(
            event_type="frontdesk_handoff",
            recipient_id=None,
            recipient_email=str(to),
            subject=subject,
            text_body=body,
            priority="high",
        )
    except Exception:
        return False
    await query(
        db, "UPDATE frontdesk_sessions SET handoff_notified_at=NOW(), updated_at=NOW() WHERE id=:id",
        {"id": str(session["id"])},
    )
    return True

_WAITING_HOLD = ("Thanks for waiting — I've asked a team member to join us. "
                 "They'll be with you in just a few minutes.")

async def _handoff_wait_reply(db: PostgresClient, email_service: MailjetEmailService, session: dict) -> str:
    """What to tell a waiting visitor, evaluated on their turn.

    There is no scheduler, so the window is judged whenever the visitor speaks:
    still ticking means ask them to hold, lapsed means promise the follow-up and
    send the email that makes the promise true.
    """
    if not _wait_elapsed(session):
        return _WAITING_HOLD
    if session.get("handoff_notified_at"):
        return ("A team member has your conversation and will follow up with you by email. "
                "Anything you add here will reach them too.")
    emailed = await _email_visitor(
        db, email_service, session,
        subject="We'll get back to you shortly",
        body=(
            f"Hi {session.get('contact_name') or 'there'},\n\n"
            "Thanks for getting in touch. Nobody was free to join your chat just now, so a member of "
            "our team will follow up with you here by email shortly.\n\n"
            "You can reply to this message with anything else you'd like us to know.\n"
        ),
    )
    if emailed:
        return ("Nobody is free to join right now, so I've made sure a team member will follow up with you. "
                f"You'll get an email at {session.get('contact_email')} shortly.")
    return ("Nobody is free to join right now, but a team member will follow up with you shortly. "
            "If you share your email address I'll make sure the reply reaches you there.")

async def _ai_turn_events(db: PostgresClient, session_id: UUID, content: str, email_service: MailjetEmailService | None = None):
    """Shared visitor-turn pipeline: history -> AI stream -> persist reply.

    Emits SSE token events; guarantees an assistant message is persisted even
    when the AI service is unreachable (visitor is routed to a human instead of
    losing the turn).
    """
    session = await _require_session(db, session_id)
    if session.get("mode") == "human_live":
        # A teammate has joined this conversation: the AI stays silent and the
        # visitor's message simply waits for the human reply.
        yield f"event: done\ndata: {json.dumps({'human_live': True})}\n\n"
        return
    if session.get("handoff_wait_until") and email_service is not None:
        # Waiting on a human: hold the visitor, or promise the email follow-up
        # once the window has lapsed. The AI does not re-enter the conversation.
        reply = await _handoff_wait_reply(db, email_service, session)
        await _persist_message(db, session_id, "outbound", "frontdesk_agent", reply)
        for token in reply.split(" "):
            yield f"event: token\ndata: {json.dumps({'token': token + ' '})}\n\n"
            await asyncio.sleep(0)
        yield f"event: done\ndata: {json.dumps({'waiting_human': True})}\n\n"
        return
    history = await _ai_history(db, session_id)
    reply = "I'm sorry, I'm unable to respond right now. A team member will follow up shortly."
    reply_parts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream(
                "POST",
                f"{settings.AI_SERVICE_BASE_URL}/frontdesk/chat/stream",
                json={"session_id": str(session_id), "message": content, "history": history},
                headers=_ai_headers(),
            ) as response:
                response.raise_for_status()
                event, data = "", []
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].strip())
                    elif not line and data:
                        raw, data = "\n".join(data), []
                        try:
                            item = json.loads(raw)
                        except Exception:
                            item = {}
                        kind = item.get("type") or event
                        if kind == "token":
                            chunk = item.get("token") or item.get("text") or ""
                            reply_parts.append(chunk)
                            yield f"event: token\ndata: {json.dumps({'token': chunk})}\n\n"
                        event = ""
        reply = "".join(reply_parts) or reply
    except Exception:
        await _mark_agent_unavailable(db, session_id)
    await _persist_message(db, session_id, "outbound", "frontdesk_agent", reply)
    if not reply_parts:
        for token in reply.split(" "):
            yield f"event: token\ndata: {json.dumps({'token': token + ' '})}\n\n"
            await asyncio.sleep(0)
    yield "event: done\ndata: {}\n\n"

# ---------------------------------------------------------------------------
# Employee workspace
# ---------------------------------------------------------------------------

@router.get("/sessions", response_model=list[FrontDeskSessionResponse])
async def list_sessions(db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    await ensure_tables(db)
    return await query(db, f"{_SESSION_SELECT} ORDER BY s.updated_at DESC LIMIT 100", many=True)

@router.post("/sessions", response_model=FrontDeskSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(payload: FrontDeskSessionCreate, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    await ensure_tables(db)
    return await query(
        db,
        "INSERT INTO frontdesk_sessions(channel, contact_name, contact_email) VALUES (:channel,:name,:email) RETURNING *",
        {"channel": payload.channel, "name": payload.name, "email": payload.email},
    )

@router.get("/sessions/{session_id}", response_model=FrontDeskSessionDetail)
async def get_session(session_id: UUID, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    await ensure_tables(db)
    session = await _require_session(db, session_id)
    session["messages"] = await query(
        db, "SELECT * FROM frontdesk_messages WHERE session_id=:id ORDER BY created_at", {"id": str(session_id)}, many=True
    )
    return session

@router.post("/sessions/{session_id}/messages", response_model=FrontDeskMessageResponse)
async def add_message(session_id: UUID, payload: FrontDeskMessageCreate, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    """Non-streaming turn. Employees may also use direction='outbound' to take over."""
    await ensure_tables(db)
    session = await _require_session(db, session_id)
    if payload.direction == "outbound":
        return await _persist_message(db, session_id, "outbound", "staff", payload.content)
    message = await _persist_message(db, session_id, "inbound", "visitor", payload.content)
    if session.get("mode") == "human_live":
        return message
    try:
        history = await _ai_history(db, session_id)
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{settings.AI_SERVICE_BASE_URL}/frontdesk/chat",
                json={"session_id": str(session_id), "message": payload.content, "history": history},
                headers=_ai_headers(),
            )
        response.raise_for_status()
        reply = response.json().get("reply") or "I will connect you with a team member."
    except Exception:
        await _mark_agent_unavailable(db, session_id)
        reply = "I'm sorry, I'm unable to respond right now. A team member will follow up."
    await _persist_message(db, session_id, "outbound", "frontdesk_agent", reply)
    return message

@router.post("/sessions/{session_id}/messages/stream")
async def stream_message(session_id: UUID, payload: FrontDeskMessageCreate, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth), email_service: MailjetEmailService = Depends(get_email_service)):
    await ensure_tables(db)
    await _require_session(db, session_id)
    await _persist_message(db, session_id, "inbound", "visitor", payload.content)
    return StreamingResponse(
        _ai_turn_events(db, session_id, payload.content, email_service),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.post("/sessions/{session_id}/identity", response_model=FrontDeskSessionResponse)
async def resolve_identity(session_id: UUID, payload: FrontDeskIdentityRequest, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    await ensure_tables(db)
    await _require_session(db, session_id)
    lead = None
    if payload.email:
        lead = await query(
            db, "SELECT id,name,email,company,owner_id FROM leads WHERE lower(email)=lower(:email) LIMIT 1", {"email": payload.email.strip()}
        )
    if not lead and payload.phone:
        lead = await query(
            db,
            "SELECT id,name,email,company,owner_id FROM leads WHERE regexp_replace(phone,'[^0-9]','','g')=regexp_replace(:phone,'[^0-9]','','g') LIMIT 1",
            {"phone": payload.phone},
        )
    if lead:
        return await query(
            db,
            """UPDATE frontdesk_sessions SET contact_type='lead',contact_id=:cid,contact_name=:name,contact_email=:email,
               lead_owner_id=:owner,identity_status='matched',identity_confidence=1,mode='known_contact',updated_at=NOW()
               WHERE id=:id RETURNING *""",
            {"id": str(session_id), "cid": str(lead["id"]), "name": lead.get("name"), "email": lead.get("email"), "owner": str(lead["owner_id"]) if lead.get("owner_id") else None},
        )
    return await query(
        db,
        """UPDATE frontdesk_sessions SET contact_name=COALESCE(:name,contact_name),contact_email=COALESCE(:email,contact_email),
           identity_status='unmatched',identity_confidence=0,updated_at=NOW() WHERE id=:id RETURNING *""",
        {"id": str(session_id), "name": payload.name, "email": payload.email},
    )

@router.post("/sessions/{session_id}/discovery", response_model=FrontDeskSessionResponse)
async def save_discovery(session_id: UUID, payload: FrontDeskDiscoveryFactsRequest, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    await ensure_tables(db)
    row = await query(
        db,
        """UPDATE frontdesk_sessions SET mode='discovery', discovery_stage=COALESCE(:stage,discovery_stage),
           discovery_facts=COALESCE(discovery_facts,'{}'::jsonb)||CAST(:facts AS jsonb), updated_at=NOW()
           WHERE id=:id RETURNING *""",
        {"id": str(session_id), "stage": payload.stage, "facts": json.dumps(payload.facts)},
    )
    if not row:
        raise HTTPException(404, "Front-desk session not found")
    return row

@router.post("/sessions/{session_id}/handoff", response_model=FrontDeskSessionResponse)
async def handoff(session_id: UUID, payload: FrontDeskHandoffRequest, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    await ensure_tables(db)
    row = await query(
        db,
        """UPDATE frontdesk_sessions SET status='waiting_human', mode='human_handoff', handoff_status='open',
           handoff_reason=:reason, intent=COALESCE(:intent,intent), urgency=:urgency,
           handoff_wait_until=NOW() + make_interval(mins => :wait), handoff_notified_at=NULL, updated_at=NOW()
           WHERE id=:id RETURNING *""",
        {"id": str(session_id), "reason": payload.reason, "intent": payload.intent, "urgency": payload.urgency,
         "wait": settings.FRONTDESK_HANDOFF_WAIT_MINUTES},
    )
    if not row:
        raise HTTPException(404, "Front-desk session not found")
    await query(
        db, "INSERT INTO frontdesk_handoffs(session_id,reason,urgency) VALUES (:sid,:reason,:urgency)",
        {"sid": str(session_id), "reason": payload.reason, "urgency": payload.urgency},
    )
    return row

@router.post("/sessions/{session_id}/takeover", response_model=FrontDeskSessionResponse)
async def takeover(
    session_id: UUID,
    db: PostgresClient = Depends(get_db),
    current_user: dict = Depends(require_auth),
    email_service: MailjetEmailService = Depends(get_email_service),
):
    """A human joins the chat: the AI stops replying to this session from now on.

    If the visitor was told to wait and that window has already lapsed they are
    very likely gone from the page, so they get an email saying someone is now
    looking at their question. Joining inside the window sends nothing — the rep
    is here in time and answers in the chat.
    """
    await ensure_tables(db)
    session = await _require_session(db, session_id)
    await query(
        db,
        """UPDATE frontdesk_sessions SET mode='human_live', status='human_live', handoff_status='claimed',
           handoff_assigned_to=:agent, updated_at=NOW() WHERE id=:id""",
        {"id": str(session_id), "agent": str(current_user["id"])},
    )
    if _wait_elapsed(session) and not session.get("handoff_notified_at"):
        await _email_visitor(
            db, email_service, session,
            subject="We're looking at your question",
            body=(
                f"Hi {session.get('contact_name') or 'there'},\n\n"
                f"{current_user.get('full_name') or 'A member of our team'} has picked up your conversation "
                "and will reply shortly. You can reply to this email, or return to the chat to continue there.\n\n"
                "Thanks for your patience.\n"
            ),
        )
    return await _require_session(db, session_id)

@router.post("/sessions/{session_id}/close", response_model=FrontDeskSessionResponse)
async def close_session(session_id: UUID, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    """Finish a conversation. Any open handoff is resolved with it."""
    await ensure_tables(db)
    await _require_session(db, session_id)
    await query(
        db,
        """UPDATE frontdesk_sessions SET status='closed', handoff_status='resolved', handoff_wait_until=NULL,
           closed_at=NOW(), closed_by=:agent, updated_at=NOW() WHERE id=:id""",
        {"id": str(session_id), "agent": str(current_user["id"])},
    )
    await query(
        db,
        "UPDATE frontdesk_handoffs SET status='resolved', resolved_at=NOW() WHERE session_id=:sid AND status='open'",
        {"sid": str(session_id)},
    )
    return await _require_session(db, session_id)

@router.post("/sessions/{session_id}/reopen", response_model=FrontDeskSessionResponse)
async def reopen_session(session_id: UUID, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    """Return a closed or taken-over chat to the AI.

    This is also the only way back from `human_live`: it clears `mode`, so the
    agent answers the visitor again instead of the chat being dead for good.
    """
    await ensure_tables(db)
    await _require_session(db, session_id)
    await query(
        db,
        """UPDATE frontdesk_sessions SET status='active', mode='frontdesk', handoff_status=NULL,
           handoff_wait_until=NULL, handoff_notified_at=NULL, closed_at=NULL, closed_by=NULL,
           updated_at=NOW() WHERE id=:id""",
        {"id": str(session_id)},
    )
    return await _require_session(db, session_id)

@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: UUID, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    """Erase a conversation and its transcript. Managers and admins only.

    Messages, handoffs and appointments cascade from the session FK. Leads,
    tasks and notes the conversation produced are CRM records and stay.
    """
    if str(current_user.get("role") or "") not in ("admin", "sales_manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can delete a conversation")
    await ensure_tables(db)
    await _require_session(db, session_id)
    await query(db, "DELETE FROM frontdesk_sessions WHERE id=:id", {"id": str(session_id)})
    return None

@router.post("/sessions/{session_id}/book", response_model=dict)
async def book_meeting(session_id: UUID, payload: FrontDeskBookingRequest, db: PostgresClient = Depends(get_db), current_user: dict = Depends(require_auth)):
    await ensure_tables(db)
    session = await _require_session(db, session_id)
    if not session.get("contact_id") or session.get("contact_type") != "lead":
        raise HTTPException(400, "A matched lead is required before booking")
    appointment = await query(
        db,
        """INSERT INTO frontdesk_appointments(session_id,lead_id,owner_id,title,notes,starts_at,ends_at)
           VALUES (:sid,:lead,:owner,:title,:notes,:starts,:ends) RETURNING *""",
        {"sid": str(session_id), "lead": str(session["contact_id"]), "owner": str(session.get("lead_owner_id")) if session.get("lead_owner_id") else None, "title": payload.title, "notes": payload.notes, "starts": payload.starts_at, "ends": payload.ends_at},
    )
    task = await query(
        db,
        """INSERT INTO tasks(entity_type,entity_id,title,description,assigned_to,status,priority,source)
           VALUES ('lead',:lead,:title,:description,:owner,'backlog','medium','frontdesk') RETURNING id""",
        {"lead": str(session["contact_id"]), "title": f"Prepare for {payload.title}", "description": payload.notes or "Meeting booked by front desk agent.", "owner": str(session.get("lead_owner_id")) if session.get("lead_owner_id") else None},
    )
    return {"appointment": appointment, "task_id": task.get("id") if task else None}

# ---------------------------------------------------------------------------
# Inbound email channel
# ---------------------------------------------------------------------------

@router.post("/webhooks/email", status_code=status.HTTP_202_ACCEPTED)
async def receive_email(payload: FrontDeskEmailWebhook, db: PostgresClient = Depends(get_db), x_frontdesk_webhook_token: str | None = Header(default=None)):
    await ensure_tables(db)
    session = await query(
        db,
        "SELECT * FROM frontdesk_sessions WHERE contact_email=:email AND status IN ('active','waiting_human') ORDER BY updated_at DESC LIMIT 1",
        {"email": payload.sender_email},
    )
    if not session:
        session = await query(
            db,
            "INSERT INTO frontdesk_sessions(channel,contact_name,contact_email) VALUES ('email',:name,:email) RETURNING *",
            {"name": payload.sender_name, "email": payload.sender_email},
        )
    await _persist_message(db, UUID(str(session["id"])), "inbound", "visitor", f"Subject: {payload.subject or '(no subject)'}\n\n{payload.body}")
    return {"session_id": str(session["id"]), "status": "accepted"}

# ---------------------------------------------------------------------------
# Public customer chat (visitor-token authenticated, no CRM login)
# ---------------------------------------------------------------------------

@router.post("/public/sessions", response_model=PublicSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_public_session(payload: PublicSessionCreate, db: PostgresClient = Depends(get_db)):
    if not payload.consent:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Consent to the privacy notice is required before starting a chat")
    await ensure_tables(db)
    raw_token, token_hash = new_visitor_token()
    session = await query(
        db,
        """INSERT INTO frontdesk_sessions(channel, contact_name, contact_email, visitor_token_hash, consent_accepted_at)
           VALUES ('web_chat_public', :name, :email, :token, NOW()) RETURNING *""",
        {"name": payload.name, "email": payload.email, "token": token_hash},
    )
    return PublicSessionResponse(
        session_id=session["id"],
        visitor_token=raw_token,
        channel=session["channel"],
        contact_name=session.get("contact_name"),
        contact_email=session.get("contact_email"),
        status=session["status"],
        created_at=session["created_at"],
    )

@router.get("/public/sessions/{session_id}", response_model=PublicSessionDetail)
async def get_public_session(
    session_id: UUID,
    db: PostgresClient = Depends(get_db),
    x_visitor_token: str | None = Header(default=None),
):
    """Customer-safe view: visitor + agent messages only. Staff notes, CRM links,
    routing state, and discovery internals are never exposed."""
    await ensure_tables(db)
    session = await _require_visitor_session(db, session_id, x_visitor_token)
    messages = await query(
        db,
        """SELECT id, direction, sender_type, content, created_at FROM frontdesk_messages
           WHERE session_id=:id AND sender_type IN ('visitor','frontdesk_agent') ORDER BY created_at""",
        {"id": str(session_id)},
        many=True,
    )
    return PublicSessionDetail(
        session_id=session["id"],
        channel=session["channel"],
        status=session["status"],
        contact_name=session.get("contact_name"),
        contact_email=session.get("contact_email"),
        summary=session.get("summary"),
        messages=messages or [],
        created_at=session["created_at"],
    )

@router.post("/public/sessions/{session_id}/messages/stream")
async def stream_public_message(
    session_id: UUID,
    payload: FrontDeskMessageCreate,
    db: PostgresClient = Depends(get_db),
    x_visitor_token: str | None = Header(default=None),
    email_service: MailjetEmailService = Depends(get_email_service),
):
    await ensure_tables(db)
    await _require_visitor_session(db, session_id, x_visitor_token)
    await _persist_message(db, session_id, "inbound", "visitor", payload.content)
    return StreamingResponse(
        _ai_turn_events(db, session_id, payload.content, email_service),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
