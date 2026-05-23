from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.utils import hash_password
from app.database import get_db
from app.schemas.invite import InviteAcceptRequest, InviteAcceptResponse, InviteValidationResponse
from app.services.email_service import MailjetEmailService
from app.services.invite_service import InviteService
from app.postgres_client import PostgresClient

router = APIRouter()


def _display_role(role: str | None) -> str:
    role_value = str(role or "").strip().lower()
    if role_value == "sales_manager":
        return "manager"
    if role_value == "sales_rep":
        return "sales_rep"
    return role_value or "sales_rep"


def get_invite_service(
    db: PostgresClient = Depends(get_db),
) -> InviteService:
    return InviteService(db, email_service=MailjetEmailService(db))


@router.get("/validate", response_model=InviteValidationResponse)
async def validate_invite(
    token: str,
    service: InviteService = Depends(get_invite_service),
):
    invite = await service.validate_invite(token)
    return {
        "email": invite.get("email"),
        "role": _display_role(invite.get("role")),
        "expires_at": invite.get("expires_at"),
        "invited_by": invite.get("invited_by_name"),
    }


@router.post("/accept", response_model=InviteAcceptResponse)
async def accept_invite(
    payload: InviteAcceptRequest,
    service: InviteService = Depends(get_invite_service),
):
    updated = await service.accept_invite(payload.token, payload.full_name, hash_password(payload.password))
    return {
        "user_id": updated.get("id"),
        "email": updated.get("email"),
        "role": updated.get("role"),
    }
