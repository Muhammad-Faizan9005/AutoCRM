from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text

from app.config import settings
from app.database import run_db_operation
from app.postgres_client import PostgresClient
from app.services.email_service import MailjetEmailService
from app.services.registration_service import normalize_role_input
from app.auth.utils import hash_password


class InviteService:
    def __init__(self, db: PostgresClient, email_service: MailjetEmailService | None = None):
        self.db = db
        self.email_service = email_service or MailjetEmailService(db)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _expires_at(self) -> datetime:
        hours = max(1, int(settings.INVITE_TOKEN_TTL_HOURS))
        return self._now() + timedelta(hours=hours)

    def _invite_link(self, token: str) -> str:
        base = settings.FRONTEND_BASE_URL.rstrip("/")
        return f"{base}/accept-invite?token={token}"

    @staticmethod
    def _display_role(role: str) -> str:
        role_value = role.strip().lower()
        if role_value == "sales_manager":
            return "manager"
        if role_value == "sales_rep":
            return "sales_rep"
        return role_value

    async def create_invite(
        self,
        *,
        agent_id: str,
        email: str,
        role: str,
        invited_by: str | None,
    ) -> None:
        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)
        expires_at = self._expires_at()
        role_value = normalize_role_input(role) or role
        role_label = self._display_role(role_value)

        def _insert():
            with self.db.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO agent_invites "
                        "(agent_id, invited_by, email, role, token_hash, expires_at) "
                        "VALUES (:agent_id, :invited_by, :email, :role, :token_hash, :expires_at)"
                    ),
                    {
                        "agent_id": agent_id,
                        "invited_by": invited_by,
                        "email": email,
                        "role": role_value,
                        "token_hash": token_hash,
                        "expires_at": expires_at,
                    },
                )

        await run_db_operation(_insert)
        invite_link = self._invite_link(token)
        try:
            await self.email_service.send_invite_email(
                recipient_email=email,
                role=role_label,
                invite_link=invite_link,
            )
        except Exception as exc:
            await self.revoke_invited_user(agent_id, reason="send_failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to send invite email",
            ) from exc

    async def validate_invite(self, token: str) -> dict[str, Any]:
        token_hash = self._hash_token(token)

        def _query():
            with self.db.engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT i.id, i.agent_id, i.email, i.role, i.expires_at, i.revoked_at, i.accepted_at, "
                        "a.status, inviter.full_name AS invited_by_name "
                        "FROM agent_invites i "
                        "JOIN agents a ON a.id = i.agent_id "
                        "LEFT JOIN agents inviter ON inviter.id = i.invited_by "
                        "WHERE i.token_hash = :token_hash"
                    ),
                    {"token_hash": token_hash},
                ).mappings().first()
                return dict(row) if row else None

        row = await run_db_operation(_query)
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

        if row.get("revoked_at") is not None:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite has been revoked")
        if row.get("accepted_at") is not None:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite already accepted")
        if row.get("expires_at") and row.get("expires_at") < self._now():
            await self._fail_invite_by_token(token_hash, reason="expired")
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite has expired")

        if str(row.get("status")) == "disabled":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invite is no longer active")

        return row

    async def accept_invite(self, token: str, full_name: str, password_hash: str) -> dict[str, Any]:
        token_hash = self._hash_token(token)
        invite = await self.validate_invite(token)
        agent_id = str(invite.get("agent_id"))

        def _update():
            with self.db.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE agents "
                        "SET full_name = :full_name, password_hash = :password_hash, status = 'active', is_active = true "
                        "WHERE id = :agent_id"
                    ),
                    {
                        "agent_id": agent_id,
                        "full_name": full_name,
                        "password_hash": password_hash,
                    },
                )
                conn.execute(
                    text(
                        "UPDATE agent_invites "
                        "SET accepted_at = NOW() "
                        "WHERE token_hash = :token_hash"
                    ),
                    {"token_hash": token_hash},
                )
                conn.execute(
                    text(
                        "UPDATE agent_invites "
                        "SET revoked_at = NOW() "
                        "WHERE agent_id = :agent_id AND accepted_at IS NULL AND token_hash != :token_hash"
                    ),
                    {"agent_id": agent_id, "token_hash": token_hash},
                )
                row = conn.execute(
                    text("SELECT id, email, role FROM agents WHERE id = :agent_id"),
                    {"agent_id": agent_id},
                ).mappings().first()
                return dict(row) if row else None

        updated = await run_db_operation(_update)
        if not updated:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invite acceptance failed")
        await self.email_service.ensure_preferences(str(updated.get("id")), str(updated.get("role") or "sales_rep"))
        return updated

    async def cleanup_expired_invites(self) -> int:
        now = self._now()

        def _query():
            with self.db.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT i.agent_id, i.email, i.role, i.invited_by, a.full_name, a.team_id "
                        "FROM agent_invites i "
                        "JOIN agents a ON a.id = i.agent_id "
                        "WHERE i.accepted_at IS NULL AND i.revoked_at IS NULL "
                        "AND i.expires_at < :now AND a.status = 'invited'"
                    ),
                    {"now": now},
                ).mappings().all()
                return [dict(row) for row in rows]

        expired = await run_db_operation(_query)
        for row in expired:
            await self._record_failed_invite(row, reason="expired")
            await self._delete_invited_user(str(row.get("agent_id")))
        return len(expired)

    async def revoke_invited_user(self, agent_id: str, *, reason: str = "revoked") -> None:
        row = await self._get_invited_agent_details(agent_id)
        if not row:
            return
        await self._record_failed_invite(row, reason=reason)
        await self._delete_invited_user(agent_id)

    async def reinvite_failed_invite(
        self,
        failed_id: str,
        *,
        inviter_id: str | None,
        require_team_for_rep: bool,
        fallback_team_id: str | None,
    ) -> dict[str, Any]:
        failed = await self._get_failed_invite(failed_id)
        if not failed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Failed invite not found")

        role_value = normalize_role_input(str(failed.get("role"))) or str(failed.get("role"))
        team_id = str(failed.get("team_id") or "") or None
        if role_value == "sales_rep":
            team_id = team_id or fallback_team_id
            if require_team_for_rep and not team_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="team_id is required to reinvite a sales rep",
                )

        full_name = str(failed.get("full_name") or failed.get("email") or "Invited User")

        new_user = await self._create_invited_user(
            email=str(failed.get("email")),
            full_name=full_name,
            role=role_value,
        )

        if team_id and role_value == "sales_rep":
            await self._assign_team(team_id, str(new_user.get("id")))

        await self.create_invite(
            agent_id=str(new_user.get("id")),
            email=str(new_user.get("email")),
            role=str(new_user.get("role")),
            invited_by=inviter_id,
        )
        await self._delete_failed_invite(failed_id)
        return new_user

    async def _get_invited_agent_details(self, agent_id: str) -> dict[str, Any] | None:
        def _query():
            with self.db.engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT a.id AS agent_id, a.email, a.full_name, a.role, a.team_id, i.invited_by "
                        "FROM agents a "
                        "LEFT JOIN agent_invites i ON i.agent_id = a.id "
                        "WHERE a.id = :agent_id AND a.status = 'invited'"
                    ),
                    {"agent_id": agent_id},
                ).mappings().first()
                return dict(row) if row else None

        return await run_db_operation(_query)

    async def _record_failed_invite(self, row: dict[str, Any], *, reason: str) -> None:
        def _insert():
            with self.db.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO failed_invites "
                        "(agent_id, email, full_name, role, team_id, invited_by, reason) "
                        "VALUES (:agent_id, :email, :full_name, :role, :team_id, :invited_by, :reason)"
                    ),
                    {
                        "agent_id": row.get("agent_id"),
                        "email": row.get("email"),
                        "full_name": row.get("full_name"),
                        "role": row.get("role"),
                        "team_id": row.get("team_id"),
                        "invited_by": row.get("invited_by"),
                        "reason": reason,
                    },
                )

        await run_db_operation(_insert)

    async def _delete_invited_user(self, agent_id: str) -> None:
        def _delete():
            with self.db.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM agent_invites WHERE agent_id = :agent_id"),
                    {"agent_id": agent_id},
                )
                conn.execute(
                    text("DELETE FROM agents WHERE id = :agent_id"),
                    {"agent_id": agent_id},
                )

        await run_db_operation(_delete)

    async def _fail_invite_by_token(self, token_hash: str, *, reason: str) -> None:
        def _query():
            with self.db.engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT a.id AS agent_id, a.email, a.full_name, a.role, a.team_id, i.invited_by "
                        "FROM agent_invites i "
                        "JOIN agents a ON a.id = i.agent_id "
                        "WHERE i.token_hash = :token_hash AND a.status = 'invited'"
                    ),
                    {"token_hash": token_hash},
                ).mappings().first()
                return dict(row) if row else None

        row = await run_db_operation(_query)
        if not row:
            return
        await self._record_failed_invite(row, reason=reason)
        await self._delete_invited_user(str(row.get("agent_id")))

    async def _get_failed_invite(self, failed_id: str) -> dict[str, Any] | None:
        def _query():
            with self.db.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT * FROM failed_invites WHERE id = :id"),
                    {"id": failed_id},
                ).mappings().first()
                return dict(row) if row else None

        return await run_db_operation(_query)

    async def get_failed_invite(self, failed_id: str) -> dict[str, Any] | None:
        return await self._get_failed_invite(failed_id)

    async def _delete_failed_invite(self, failed_id: str) -> None:
        def _delete():
            with self.db.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM failed_invites WHERE id = :id"),
                    {"id": failed_id},
                )

        await run_db_operation(_delete)

    async def delete_failed_invite(self, failed_id: str) -> None:
        await self._delete_failed_invite(failed_id)

    async def _assign_team(self, team_id: str, agent_id: str) -> None:
        def _exec():
            with self.db.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO team_members (team_id, agent_id) "
                        "VALUES (:tid, :aid) ON CONFLICT DO NOTHING"
                    ),
                    {"tid": team_id, "aid": agent_id},
                )
                conn.execute(
                    text("UPDATE agents SET team_id = :tid WHERE id = :aid"),
                    {"tid": team_id, "aid": agent_id},
                )

        await run_db_operation(_exec)

    async def _create_invited_user(self, *, email: str, full_name: str, role: str) -> dict[str, Any]:
        role_value = normalize_role_input(role) or role
        new_user = {
            "email": email,
            "full_name": full_name,
            "role": role_value,
            "password_hash": hash_password(secrets.token_urlsafe(16)),
            "is_active": False,
            "status": "invited",
        }

        def _insert():
            with self.db.engine.begin() as conn:
                row = conn.execute(
                    text(
                        "INSERT INTO agents (id, email, password_hash, full_name, role, is_active, status) "
                        "VALUES (uuid_generate_v4(), :email, :password_hash, :full_name, :role, :is_active, :status) "
                        "RETURNING id, email, role"
                    ),
                    new_user,
                ).mappings().first()
                return dict(row) if row else None

        created = await run_db_operation(_insert)
        if not created:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to recreate invite")
        return created
