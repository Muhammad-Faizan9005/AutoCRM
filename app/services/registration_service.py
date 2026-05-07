from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from supabase import Client

from app.auth.utils import hash_password
from app.database import run_db_operation
from app.utils.sanitization import sanitize_payload

ROLE_INPUT_MAP = {
    "admin": "admin",
    "administrator": "admin",
    "system_manager": "admin",
    "superuser": "admin",
    "manager": "sales_manager",
    "sales_manager": "sales_manager",
    "agent": "sales_rep",
    "sales_rep": "sales_rep",
}


def normalize_role_input(role: str | None) -> str | None:
    if role is None:
        return None
    normalized = role.strip().lower().replace("-", "_").replace(" ", "_")
    return ROLE_INPUT_MAP.get(normalized)


async def register_user_account(
    db: Client,
    *,
    email: str,
    password: str,
    full_name: str,
    role: str = "sales_rep",
    is_active: bool = True,
    status_value: str | None = None,
) -> dict[str, Any]:
    sanitized_payload = sanitize_payload({"email": email, "full_name": full_name})

    normalized_role = normalize_role_input(role)
    if not normalized_role:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported role",
        )

    existing_user = await run_db_operation(
        lambda: db.table("agents").select("id").eq("email", sanitized_payload["email"]).limit(1).execute()
    )
    if existing_user.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    new_user = {
        "id": str(uuid.uuid4()),
        "email": sanitized_payload["email"],
        "password_hash": hash_password(password),
        "full_name": sanitized_payload["full_name"],
        "role": normalized_role,
        "is_active": is_active,
    }
    if status_value is not None:
        new_user["status"] = status_value

    response = await run_db_operation(lambda: db.table("agents").insert(new_user).execute())
    rows = response.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )

    return rows[0]
