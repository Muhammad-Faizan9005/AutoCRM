from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect, status
from supabase import Client

from app.auth.dependencies import require_auth
from app.config import settings
from app.database import get_db, run_db_operation
from app.repositories.call_repository import CallRepository
from app.schemas.call import CallRecordingResponse, CallSessionResponse, CallStartRequest, CallStartResponse
from app.services.ai_transcription_client import AITranscriptionClient
from app.services.email_service import MailjetEmailService
from sqlalchemy import text
from app.utils.team_access import can_access_lead


logger = logging.getLogger("autocrm")

router = APIRouter()


def get_call_repository(db: Client = Depends(get_db)) -> CallRepository:
    return CallRepository(db)


def get_email_service(db: Client = Depends(get_db)) -> MailjetEmailService:
    return MailjetEmailService(db)


def _hash_room_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_room_token() -> str:
    return secrets.token_urlsafe(32)


def _recording_storage_path(call_id: str, extension: str) -> str:
    filename = f"call_{call_id}.{extension}"
    return str(_recordings_dir() / filename)


def _recordings_dir() -> Path:
    return Path(settings.CALL_RECORDINGS_DIR).expanduser().resolve()


def _recording_tmp_dir(call_id: str) -> Path:
    return _recordings_dir() / "tmp" / call_id


def _safe_recording_extension(value: str | None) -> str:
    extension = (value or "webm").strip().lower().lstrip(".")
    if extension not in {"webm", "ogg", "mp3", "wav", "m4a"}:
        return "webm"
    return extension


def _recording_db_path(call_id: str, extension: str) -> str:
    return f"recordings/call_{call_id}.{extension}"


def _recording_url(call_id: str, extension: str) -> str:
    return f"{settings.CALL_RECORDINGS_URL_BASE}/call_{call_id}.{extension}"


async def _assert_can_use_call(db: Client, repository: CallRepository, current_user: dict, call_id: UUID) -> dict[str, Any]:
    existing = await repository.get_by_id(call_id)
    lead_id = existing.get("lead_id")
    if lead_id:
        await _assert_can_view_lead(db, current_user, str(lead_id))
    return existing


async def _finalize_recording_from_chunks(
    *,
    call_id: UUID,
    lead_id: str | None,
    actor_id: str | None,
    extension: str,
    mime_type: str | None,
    db: Client,
    repository: CallRepository,
) -> None:
    call_key = str(call_id)
    extension = _safe_recording_extension(extension)
    tmp_dir = _recording_tmp_dir(call_key)
    final_path = Path(_recording_storage_path(call_key, extension))
    db_path = _recording_db_path(call_key, extension)

    try:
        chunks = sorted(tmp_dir.glob("chunk_*.part"))
        if not chunks:
            await repository.update_by_id(call_id, {"processing_status": "failed"})
            logger.warning("call_recording_finalize_failed call_id=%s reason=no_chunks", call_id)
            return

        final_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path = final_path.with_suffix(final_path.suffix + ".partial")
        with partial_path.open("wb") as destination:
            for chunk in chunks:
                with chunk.open("rb") as source:
                    destination.write(source.read())
        partial_path.replace(final_path)

        size = final_path.stat().st_size
        updated = await repository.update_by_id(
            call_id,
            {
                "recording_path": db_path,
                "recording_mime": mime_type or f"audio/{extension}",
                "recording_size": size,
                "processing_status": "pending",
            },
        )

        for chunk in chunks:
            try:
                chunk.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

        await AITranscriptionClient().notify_recording_ready(
            recording_id=call_id,
            meeting_id=call_id,
            entity_id=UUID(str(lead_id)) if lead_id else None,
            entity_type="lead" if lead_id else "call_session",
            recording_path=updated.get("recording_path") or db_path,
            actor_id=actor_id,
            metadata={
                "call_id": call_key,
                "lead_id": str(lead_id) if lead_id else None,
                "actor_id": actor_id,
                "recording_mime": mime_type or f"audio/{extension}",
                "recording_size": size,
                "storage": "central_recordings_dir",
            },
        )
    except Exception:
        logger.exception("call_recording_finalize_failed call_id=%s", call_id)
        try:
            await repository.update_by_id(call_id, {"processing_status": "failed"})
        except Exception:
            pass


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
    if await can_access_lead(db, current_user, lead_id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


async def _create_room_token(
    *,
    db: Client,
    call_id: str,
    issued_to: str,
    ttl_minutes: int,
) -> str:
    raw_token = _generate_room_token()
    token_hash = _hash_room_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

    await run_db_operation(
        lambda: db.table("call_room_tokens")
        .insert(
            {
                "call_id": call_id,
                "issued_to": issued_to,
                "token_hash": token_hash,
                "expires_at": expires_at.isoformat(),
            }
        )
        .execute()
    )
    return raw_token


async def _validate_room_token(
    *,
    db: Client,
    room_id: str,
    token: str,
) -> dict[str, Any] | None:
    token_hash = _hash_room_token(token)
    now = datetime.now(timezone.utc).isoformat()

    def _query_token():
        return (
            db.table("call_room_tokens")
            .select("call_id, issued_to, expires_at")
            .eq("token_hash", token_hash)
            .gte("expires_at", now)
            .limit(1)
            .execute()
        )

    token_result = await run_db_operation(_query_token)
    rows = token_result.data or []
    if not rows:
        return None

    call_id = rows[0].get("call_id")
    if not call_id:
        return None

    def _query_call():
        return (
            db.table("call_sessions")
            .select("id, room_id, status")
            .eq("id", str(call_id))
            .limit(1)
            .execute()
        )

    call_result = await run_db_operation(_query_call)
    call_rows = call_result.data or []
    if not call_rows:
        return None

    call_row = call_rows[0]
    if str(call_row.get("room_id")) != room_id:
        return None

    return {
        "call_id": str(call_row.get("id")),
        "issued_to": rows[0].get("issued_to"),
        "status": call_row.get("status"),
    }


class CallSignalingManager:
    def __init__(self) -> None:
        self.rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, room_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.rooms.setdefault(room_id, set()).add(websocket)

    def disconnect(self, room_id: str, websocket: WebSocket) -> None:
        clients = self.rooms.get(room_id)
        if not clients:
            return
        clients.discard(websocket)
        if not clients:
            self.rooms.pop(room_id, None)

    def room_size(self, room_id: str) -> int:
        return len(self.rooms.get(room_id, set()))

    async def broadcast(self, room_id: str, payload: dict[str, Any], sender: WebSocket | None = None) -> None:
        clients = self.rooms.get(room_id, set())
        for client in list(clients):
            if sender is not None and client is sender:
                continue
            await client.send_json(payload)


signaling_manager = CallSignalingManager()


@router.post("/start", response_model=CallStartResponse, status_code=status.HTTP_201_CREATED)
async def start_call_session(
    payload: CallStartRequest,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: CallRepository = Depends(get_call_repository),
    email_service: MailjetEmailService = Depends(get_email_service),
):
    lead_id = str(payload.lead_id)
    await _assert_can_view_lead(db, current_user, lead_id)

    profile = await _get_lead_profile(db, lead_id)
    if not profile.get("name") and not profile.get("email"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    lead_email = profile.get("email")
    if not lead_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lead email is required to send invite")

    room_id = uuid4().hex
    now = datetime.now(timezone.utc)
    call_data = {
        "lead_id": lead_id,
        "initiated_by": str(current_user.get("id") or "") or None,
        "room_id": room_id,
        "direction": payload.direction or "outbound",
        "status": "created",
        "started_at": now.isoformat(),
    }
    created = await repository.create(call_data)

    room_token = await _create_room_token(
        db=db,
        call_id=str(created.get("id")),
        issued_to="agent",
        ttl_minutes=settings.CALL_ROOM_TOKEN_TTL_MINUTES,
    )
    invite_token = await _create_room_token(
        db=db,
        call_id=str(created.get("id")),
        issued_to="lead",
        ttl_minutes=settings.CALL_ROOM_TOKEN_TTL_MINUTES,
    )

    invite_url = f"{settings.FRONTEND_BASE_URL}/call/join?room={room_id}&token={invite_token}"

    agent_name = str(current_user.get("full_name") or current_user.get("email") or "Sales rep")
    lead_name = str(profile.get("name") or "there")
    try:
        await email_service.send_call_invite_email(
            recipient_email=lead_email,
            lead_name=lead_name,
            agent_name=agent_name,
            invite_url=invite_url,
        )
    except HTTPException:
        await repository.update_by_id(created.get("id"), {"status": "failed"})
        raise

    return CallStartResponse(
        call=CallSessionResponse(**created),
        room_token=room_token,
        invite_token=invite_token,
        invite_url=invite_url,
    )


@router.post("/{call_id}/end", response_model=CallSessionResponse)
async def end_call_session(
    call_id: UUID,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: CallRepository = Depends(get_call_repository),
):
    existing = await repository.get_by_id(call_id)
    lead_id = existing.get("lead_id")
    if lead_id:
        await _assert_can_view_lead(db, current_user, str(lead_id))

    ended_at = datetime.now(timezone.utc)
    duration_seconds = existing.get("duration_seconds")
    started_at = existing.get("started_at")
    if started_at and not duration_seconds:
        try:
            started_dt = datetime.fromisoformat(str(started_at))
            duration_seconds = int((ended_at - started_dt).total_seconds())
        except Exception:
            duration_seconds = None

    update = {
        "status": "ended",
        "ended_at": ended_at.isoformat(),
        "duration_seconds": duration_seconds,
    }
    updated = await repository.update_by_id(call_id, update)
    return CallSessionResponse(**updated)


@router.post("/{call_id}/recording/start")
async def start_call_recording_upload(
    call_id: UUID,
    extension: str = "webm",
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: CallRepository = Depends(get_call_repository),
):
    await _assert_can_use_call(db, repository, current_user, call_id)
    extension = _safe_recording_extension(extension)
    tmp_dir = _recording_tmp_dir(str(call_id))
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for existing_chunk in tmp_dir.glob("chunk_*.part"):
        try:
            existing_chunk.unlink()
        except OSError:
            pass
    await repository.update_by_id(call_id, {"processing_status": "pending"})
    return {
        "status": "ready",
        "call_id": str(call_id),
        "extension": extension,
        "recording_path": _recording_db_path(str(call_id), extension),
        "recording_url": _recording_url(str(call_id), extension),
    }


@router.post("/{call_id}/recording/chunks")
async def upload_call_recording_chunk(
    call_id: UUID,
    chunk_index: int = Form(...),
    file: UploadFile = File(...),
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: CallRepository = Depends(get_call_repository),
):
    await _assert_can_use_call(db, repository, current_user, call_id)
    if chunk_index < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid recording chunk index")

    tmp_dir = _recording_tmp_dir(str(call_id))
    tmp_dir.mkdir(parents=True, exist_ok=True)
    chunk_path = tmp_dir / f"chunk_{chunk_index:08d}.part"
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Recording chunk is empty")
    chunk_path.write_bytes(contents)
    return {"status": "stored", "call_id": str(call_id), "chunk_index": chunk_index, "size": len(contents)}


@router.post("/{call_id}/recording/complete")
async def complete_call_recording_upload(
    call_id: UUID,
    background_tasks: BackgroundTasks,
    extension: str = "webm",
    mime_type: str | None = None,
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: CallRepository = Depends(get_call_repository),
):
    existing = await _assert_can_use_call(db, repository, current_user, call_id)
    await repository.update_by_id(call_id, {"processing_status": "processing"})
    background_tasks.add_task(
        _finalize_recording_from_chunks,
        call_id=call_id,
        lead_id=str(existing.get("lead_id")) if existing.get("lead_id") else None,
        actor_id=str(current_user.get("id") or "") or None,
        extension=_safe_recording_extension(extension),
        mime_type=mime_type,
        db=db,
        repository=repository,
    )
    return {
        "status": "accepted",
        "call_id": str(call_id),
        "recording_path": _recording_db_path(str(call_id), _safe_recording_extension(extension)),
        "recording_url": _recording_url(str(call_id), _safe_recording_extension(extension)),
    }


@router.post("/{call_id}/recording", response_model=CallRecordingResponse)
async def upload_call_recording(
    call_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Client = Depends(get_db),
    current_user: dict = Depends(require_auth),
    repository: CallRepository = Depends(get_call_repository),
):
    existing = await _assert_can_use_call(db, repository, current_user, call_id)
    lead_id = existing.get("lead_id")

    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing recording file")

    _recordings_dir().mkdir(parents=True, exist_ok=True)
    extension = _safe_recording_extension(file.filename.split(".")[-1] if "." in file.filename else "webm")
    storage_path = _recording_storage_path(str(call_id), extension)

    contents = await file.read()
    with open(storage_path, "wb") as handle:
        handle.write(contents)

    recording_url = _recording_url(str(call_id), extension)
    update = {
        "recording_path": _recording_db_path(str(call_id), extension),
        "recording_mime": file.content_type,
        "recording_size": len(contents),
        "processing_status": "pending",
    }
    updated = await repository.update_by_id(call_id, update)

    background_tasks.add_task(
        AITranscriptionClient().notify_recording_ready,
        recording_id=call_id,
        meeting_id=call_id,
        entity_id=UUID(str(lead_id)) if lead_id else None,
        entity_type="lead" if lead_id else "call_session",
        recording_path=updated.get("recording_path") or storage_path,
        actor_id=str(current_user.get("id") or "") or None,
        metadata={
            "call_id": str(call_id),
            "lead_id": str(lead_id) if lead_id else None,
            "actor_id": str(current_user.get("id") or "") or None,
            "recording_mime": file.content_type,
            "recording_size": len(contents),
        },
    )

    return CallRecordingResponse(
        call_id=call_id,
        recording_url=recording_url,
        recording_path=updated.get("recording_path") or storage_path,
        recording_mime=updated.get("recording_mime"),
        recording_size=updated.get("recording_size"),
    )


@router.websocket("/ws/calls/{room_id}")
async def call_signaling_ws(websocket: WebSocket, room_id: str):
    db = get_db()
    token = websocket.query_params.get("token")
    if not token:
        logger.warning("call_ws_missing_token room_id=%s", room_id)
        await websocket.close(code=4401, reason="Missing token")
        return

    token_state = await _validate_room_token(db=db, room_id=room_id, token=token)
    if token_state is None:
        logger.warning("call_ws_invalid_token room_id=%s", room_id)
        await websocket.close(code=4401, reason="Invalid token")
        return

    if signaling_manager.room_size(room_id) >= 2:
        logger.warning("call_ws_room_full room_id=%s", room_id)
        await websocket.close(code=4403, reason="Room full")
        return

    await signaling_manager.connect(room_id, websocket)

    if signaling_manager.room_size(room_id) == 2:
        await run_db_operation(
            lambda: db.table("call_sessions")
            .update({"status": "active"})
            .eq("room_id", room_id)
            .execute()
        )
        await signaling_manager.broadcast(room_id, {"type": "ready"})

    try:
        while True:
            data = await websocket.receive_json()
            message_type = str(data.get("type") or "").lower()
            if message_type == "end":
                await signaling_manager.broadcast(room_id, {"type": "end"}, sender=websocket)
                await run_db_operation(
                    lambda: db.table("call_sessions")
                    .update({"status": "ended", "ended_at": datetime.now(timezone.utc).isoformat()})
                    .eq("room_id", room_id)
                    .execute()
                )
                break

            await signaling_manager.broadcast(room_id, data, sender=websocket)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("call_ws_error room_id=%s", room_id, exc_info=exc)
        await websocket.close(code=1011, reason="Server error")
    finally:
        signaling_manager.disconnect(room_id, websocket)
        if signaling_manager.room_size(room_id) == 0:
            await run_db_operation(
                lambda: db.table("call_sessions")
                .update({"status": "ended", "ended_at": datetime.now(timezone.utc).isoformat()})
                .eq("room_id", room_id)
                .execute()
            )
