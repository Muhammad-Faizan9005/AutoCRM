from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import text

from app.config import settings
from app.database import run_db_operation
from app.postgres_client import PostgresClient
from app.services.registration_service import normalize_role_input

MAILJET_SEND_URL = "https://api.mailjet.com/v3.1/send"
MAILJET_USER_URL = "https://api.mailjet.com/v3/REST/user"

logger = logging.getLogger(__name__)

DEFAULT_ROLE_PREFERENCES = {
    "admin": {
        "email_enabled": True,
        "lead_assigned_enabled": False,
        "task_assigned_enabled": False,
        "high_priority_override": True,
    },
    "sales_manager": {
        "email_enabled": True,
        "lead_assigned_enabled": False,
        "task_assigned_enabled": False,
        "high_priority_override": True,
    },
    "sales_rep": {
        "email_enabled": True,
        "lead_assigned_enabled": True,
        "task_assigned_enabled": True,
        "high_priority_override": True,
    },
}


class MailjetEmailService:
    def __init__(self, db: PostgresClient):
        self.db = db
        self._sender_email: str | None = settings.MAILJET_SENDER_EMAIL
        self._sender_name: str = settings.MAILJET_SENDER_NAME

    def _require_credentials(self) -> tuple[str, str]:
        api_key = settings.MAILJET_API_KEY
        secret_key = settings.MAILJET_SECRET_KEY
        if not api_key or not secret_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Mailjet credentials are not configured",
            )
        return api_key, secret_key

    def _load_sender_email(self, api_key: str, secret_key: str) -> str:
        if self._sender_email:
            return self._sender_email

        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(MAILJET_USER_URL, auth=(api_key, secret_key))
            if response.status_code == 200:
                payload = response.json()
                data = payload.get("Data") if isinstance(payload, dict) else None
                if data and isinstance(data, list):
                    email = data[0].get("Email")
                    if email:
                        self._sender_email = str(email)
                        return self._sender_email
        except httpx.HTTPError:
            pass

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mailjet sender email is not configured",
        )

    async def _log_email(
        self,
        *,
        event_type: str,
        recipient_id: str | None,
        recipient_email: str,
        status_value: str,
        provider_message_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        def _exec():
            with self.db.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO email_logs "
                        "(event_type, recipient_id, recipient_email, status, provider_message_id, payload) "
                        "VALUES (:event_type, :recipient_id, :recipient_email, :status, :provider_message_id, :payload::jsonb)"
                    ),
                    {
                        "event_type": event_type,
                        "recipient_id": recipient_id,
                        "recipient_email": recipient_email,
                        "status": status_value,
                        "provider_message_id": provider_message_id,
                        "payload": json.dumps(payload),
                    },
                )

        try:
            await run_db_operation(_exec)
        except Exception:
            # Email logging should never break the main flow.
            return

    async def _get_recipient(self, recipient_id: str) -> dict[str, Any] | None:
        def _query():
            with self.db.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT id, email, role FROM agents WHERE id = :id"),
                    {"id": recipient_id},
                ).mappings().first()
                return dict(row) if row else None

        return await run_db_operation(_query)

    async def get_recipient_email(self, recipient_id: str) -> str | None:
        recipient = await self._get_recipient(recipient_id)
        if not recipient:
            return None
        email = recipient.get("email")
        return str(email) if email else None

    async def _get_or_create_preferences(self, user_id: str, role: str) -> dict[str, Any]:
        normalized_role = normalize_role_input(role) or role
        defaults = DEFAULT_ROLE_PREFERENCES.get(normalized_role, DEFAULT_ROLE_PREFERENCES["sales_rep"])

        def _upsert():
            with self.db.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO email_preferences "
                        "(user_id, role, email_enabled, lead_assigned_enabled, task_assigned_enabled, high_priority_override) "
                        "VALUES (:user_id, :role, :email_enabled, :lead_assigned_enabled, :task_assigned_enabled, :high_priority_override) "
                        "ON CONFLICT (user_id) DO NOTHING"
                    ),
                    {"user_id": user_id, "role": normalized_role, **defaults},
                )
                row = conn.execute(
                    text("SELECT * FROM email_preferences WHERE user_id = :user_id"),
                    {"user_id": user_id},
                ).mappings().first()
                return dict(row) if row else {"user_id": user_id, "role": normalized_role, **defaults}

        return await run_db_operation(_upsert)

    async def ensure_preferences(self, user_id: str, role: str) -> None:
        await self._get_or_create_preferences(user_id, role)

    async def _can_send_event(
        self,
        *,
        recipient_id: str,
        role: str,
        event_type: str,
        priority: str,
    ) -> bool:
        if priority == "high":
            return True

        prefs = await self._get_or_create_preferences(recipient_id, role)
        if not prefs.get("email_enabled", True):
            return False

        if event_type == "lead_assigned":
            return bool(prefs.get("lead_assigned_enabled", True))
        if event_type == "task_assigned":
            return bool(prefs.get("task_assigned_enabled", True))

        return True

    async def send_email(
        self,
        *,
        event_type: str,
        recipient_id: str | None,
        recipient_email: str,
        subject: str,
        text_body: str,
        priority: str = "normal",
    ) -> None:
        api_key, secret_key = self._require_credentials()
        sender_email = self._load_sender_email(api_key, secret_key)

        if recipient_id:
            recipient = await self._get_recipient(recipient_id)
            if not recipient:
                return
            role = str(recipient.get("role") or "sales_rep")
            if not await self._can_send_event(
                recipient_id=recipient_id,
                role=role,                  
                event_type=event_type,
                priority=priority,
            ):
                return

        payload = {
            "Messages": [
                {
                    "From": {"Email": sender_email, "Name": self._sender_name},
                    "To": [{"Email": recipient_email}],
                    "Subject": subject,
                    "TextPart": text_body,
                }
            ]
        }

        provider_message_id = None
        status_value = "failed"
        try:
            with httpx.Client(timeout=15) as client:
                response = client.post(MAILJET_SEND_URL, json=payload, auth=(api_key, secret_key))

            if response.status_code in (200, 201):
                status_value = "sent"
                payload_json = response.json()
                messages = payload_json.get("Messages") if isinstance(payload_json, dict) else []
                if messages:
                    first = messages[0]
                    to_info = first.get("To") or []
                    if to_info:
                        provider_message_id = to_info[0].get("MessageID")
                logger.info(
                    "mailjet_send_ok recipient=%s sender=%s message_id=%s",
                    recipient_email,
                    sender_email,
                    provider_message_id,
                    extra={
                        "event_type": event_type,
                        "recipient_email": recipient_email,
                        "sender_email": sender_email,
                        "message_id": provider_message_id,
                    },
                )
            else:
                logger.warning(
                    "mailjet_send_failed recipient=%s sender=%s status=%s",
                    recipient_email,
                    sender_email,
                    response.status_code,
                    extra={
                        "event_type": event_type,
                        "recipient_email": recipient_email,
                        "sender_email": sender_email,
                        "status_code": response.status_code,
                        "response_text": response.text[:800],
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Mailjet send failed (HTTP {response.status_code})",
                )
        finally:
            await self._log_email(
                event_type=event_type,
                recipient_id=recipient_id,
                recipient_email=recipient_email,
                status_value=status_value,
                provider_message_id=str(provider_message_id) if provider_message_id else None,
                payload={"subject": subject, "priority": priority},
            )

    async def send_call_invite_email(
        self,
        *,
        recipient_email: str,
        lead_name: str,
        agent_name: str,
        invite_url: str,
    ) -> None:
        subject = f"AutoCRM call invite from {agent_name}"
        text_body = (
            f"Hi {lead_name},\n\n"
            f"{agent_name} is inviting you to an AutoCRM call.\n"
            f"Join here: {invite_url}\n\n"
            "If you did not expect this invite, you can ignore this email."
        )
        await self.send_email(
            event_type="call_invite",
            recipient_id=None,
            recipient_email=recipient_email,
            subject=subject,
            text_body=text_body,
            priority="high",
        )

    async def send_invite_email(
        self,
        *,
        recipient_email: str,
        role: str,
        invite_link: str,
    ) -> None:
        subject = "You are invited to AutoCRM"
        text_body = (
            "You have been invited to AutoCRM.\n\n"
            f"Role: {role}\n"
            f"Accept your invite: {invite_link}\n\n"
            "If you did not expect this, you can ignore this email."
        )
        await self.send_email(
            event_type="invite",
            recipient_id=None,
            recipient_email=recipient_email,
            subject=subject,
            text_body=text_body,
            priority="normal",
        )

    async def send_password_reset_email(
        self,
        *,
        recipient_email: str,
        reset_link: str,
        ttl_minutes: int,
    ) -> None:
        subject = "Reset your AutoCRM password"
        text_body = (
            "We received a request to reset your AutoCRM password.\n\n"
            f"Reset link (valid for {ttl_minutes} minutes): {reset_link}\n\n"
            "If you did not request this, you can ignore this email."
        )
        await self.send_email(
            event_type="password_reset",
            recipient_id=None,
            recipient_email=recipient_email,
            subject=subject,
            text_body=text_body,
            priority="high",
        )

    async def send_lead_assigned_email(
        self,
        *,
        recipient_id: str,
        recipient_email: str,
        actor_name: str,
        lead_name: str,
    ) -> None:
        subject = f"New lead assigned: {lead_name}"
        text_body = (
            f"{actor_name} assigned a new lead to you.\n\n"
            f"Lead: {lead_name}\n"
            "Please log in to AutoCRM to view the details."
        )
        await self.send_email(
            event_type="lead_assigned",
            recipient_id=recipient_id,
            recipient_email=recipient_email,
            subject=subject,
            text_body=text_body,
            priority="high",
        )

    async def send_task_assigned_email(
        self,
        *,
        recipient_id: str,
        recipient_email: str,
        actor_name: str,
        task_title: str,
    ) -> None:
        subject = f"New task assigned: {task_title}"
        text_body = (
            f"{actor_name} assigned a task to you.\n\n"
            f"Task: {task_title}\n"
            "Please log in to AutoCRM to view the details."
        )
        await self.send_email(
            event_type="task_assigned",
            recipient_id=recipient_id,
            recipient_email=recipient_email,
            subject=subject,
            text_body=text_body,
            priority="high",
        )
