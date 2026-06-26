from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

from app.config import settings

logger = logging.getLogger("autocrm")


class AITranscriptionClient:
    async def notify_recording_ready(
        self,
        *,
        recording_id: UUID,
        meeting_id: UUID,
        entity_id: UUID | None,
        entity_type: str,
        recording_path: str,
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not settings.AI_TRANSCRIPTION_NOTIFY_ENABLED:
            return
        base_url = str(settings.AI_SERVICE_BASE_URL or "").rstrip("/")
        if not base_url:
            logger.info("ai_transcription_notify_skipped reason=missing_ai_service_base_url")
            return

        payload = {
            "recording_id": str(recording_id),
            "meeting_id": str(meeting_id),
            "entity_id": str(entity_id) if entity_id else None,
            "entity_type": entity_type,
            "actor_id": actor_id,
            "source_type": "local_path",
            "recording_path": recording_path,
            "metadata": metadata or {},
        }
        try:
            headers = {}
            if settings.AI_SERVICE_WEBHOOK_TOKEN:
                headers["X-AutoCRM-AI-Webhook-Token"] = settings.AI_SERVICE_WEBHOOK_TOKEN
            async with httpx.AsyncClient(timeout=settings.AI_SERVICE_NOTIFY_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{base_url}/transcriptions/recording-ready",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except Exception as exc:
            logger.warning("ai_transcription_notify_failed recording_id=%s error=%s", recording_id, exc)
