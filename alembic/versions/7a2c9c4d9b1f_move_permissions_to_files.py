"""move_permissions_to_files

Revision ID: 7a2c9c4d9b1f
Revises: f0b9a0a3a4ce
Create Date: 2026-05-05 06:30:00.000000

"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

from app.config import settings


CRM_CORE_PERMISSIONS = (
    "dashboard",
    "leads",
    "deals",
    "contacts",
    "organizations",
    "notes",
    "tasks",
)
DATA_PERMISSIONS = ("import_data",)
ADMIN_PERMISSIONS = ("admin_panel", "admin_users", "admin_permissions")
ALL_PERMISSIONS = CRM_CORE_PERMISSIONS + DATA_PERMISSIONS + ADMIN_PERMISSIONS
ADMIN_ROLE_ALIASES = {"admin", "administrator", "system_manager", "superuser"}
TEMPLATE_FILE_NAME = "permission.json"


# revision identifiers, used by Alembic.
revision: str = "7a2c9c4d9b1f"
down_revision: Union[str, Sequence[str], None] = "f0b9a0a3a4ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _storage_dir() -> Path:
    base_dir = Path(__file__).resolve().parents[2]
    configured = Path(settings.PERMISSIONS_STORAGE_DIR)
    if configured.is_absolute():
        return configured
    return base_dir / configured


def _write_permissions_file(path: Path, permissions: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(permissions, indent=2, sort_keys=True, ensure_ascii=True)
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(path)


def _normalize_role(role: str | None) -> str:
    if not role:
        return ""
    return str(role).strip().lower().replace("-", "_").replace(" ", "_")


def _is_admin_role(role: str | None) -> bool:
    return _normalize_role(role) in ADMIN_ROLE_ALIASES


def _role_defaults(role: str | None) -> dict[str, bool]:
    normalized = _normalize_role(role)

    sales_manager_defaults = {key: True for key in CRM_CORE_PERMISSIONS}
    sales_manager_defaults.update({"import_data": True})
    for key in ADMIN_PERMISSIONS:
        sales_manager_defaults[key] = False

    sales_rep_defaults = {key: True for key in CRM_CORE_PERMISSIONS}
    sales_rep_defaults.update({"import_data": False})
    for key in ADMIN_PERMISSIONS:
        sales_rep_defaults[key] = False

    admin_defaults = {key: True for key in ALL_PERMISSIONS}

    defaults_by_role = {
        "admin": admin_defaults,
        "sales_manager": sales_manager_defaults,
        "sales_rep": sales_rep_defaults,
    }

    return dict(defaults_by_role.get(normalized, sales_rep_defaults))


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return bool(value)


def _sanitize_permissions_map(permissions: dict | None) -> dict[str, bool]:
    if not permissions:
        return {}
    sanitized: dict[str, bool] = {}
    for key, value in permissions.items():
        if key in ALL_PERMISSIONS:
            sanitized[key] = _coerce_bool(value)
    return sanitized


def _load_template_permissions() -> dict[str, bool]:
    template_path = _storage_dir() / TEMPLATE_FILE_NAME
    if not template_path.exists():
        return {key: False for key in ALL_PERMISSIONS}

    try:
        raw = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {key: False for key in ALL_PERMISSIONS}

    if isinstance(raw, dict) and "permissions" in raw:
        raw = raw.get("permissions")

    if not isinstance(raw, dict):
        return {key: False for key in ALL_PERMISSIONS}

    normalized = {key: _coerce_bool(value) for key, value in raw.items()}
    for key in ALL_PERMISSIONS:
        normalized.setdefault(key, False)
    return normalized


def _derive_permissions_for_file(role: str | None, overrides: dict | None) -> dict[str, bool]:
    permissions = _load_template_permissions()
    permissions.update(_role_defaults(role))
    permissions.update(_sanitize_permissions_map(overrides))

    if _is_admin_role(role):
        for key in ADMIN_PERMISSIONS:
            permissions[key] = True
        permissions["import_data"] = True

    return permissions


def _coerce_permissions(raw_value) -> dict:
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {column["name"] for column in inspector.get_columns("agent_permissions")}
    has_permissions = "permissions" in columns
    agent_columns: set[str] = set()
    if inspector.has_table("agents"):
        agent_columns = {column["name"] for column in inspector.get_columns("agents")}

    if "permission_file" not in columns:
        op.execute("ALTER TABLE agent_permissions ADD COLUMN IF NOT EXISTS permission_file VARCHAR(255);")

    storage_dir = _storage_dir()

    select_columns = ["ap.user_id", "ap.permission_file"]
    if has_permissions:
        select_columns.append("ap.permissions")
    if "role" in agent_columns:
        select_columns.append("a.role")

    query = "SELECT " + ", ".join(select_columns) + " FROM agent_permissions ap"
    if "role" in agent_columns:
        query += " LEFT JOIN agents a ON a.id = ap.user_id"

    rows = bind.execute(text(query)).mappings().all()

    for row in rows:
        user_id = str(row.get("user_id"))
        file_name = row.get("permission_file") or f"{user_id}.json"
        role = row.get("role") if "role" in row else None
        overrides = _coerce_permissions(row.get("permissions")) if has_permissions else {}
        permissions = _derive_permissions_for_file(role, overrides)

        file_path = storage_dir / file_name
        _write_permissions_file(file_path, permissions)

        if row.get("permission_file") != file_name:
            bind.execute(
                text(
                    "UPDATE agent_permissions SET permission_file = :file_name WHERE user_id = :user_id"
                ),
                {"file_name": file_name, "user_id": user_id},
            )

    if has_permissions:
        op.execute("ALTER TABLE agent_permissions DROP COLUMN IF EXISTS permissions;")

    op.execute("ALTER TABLE agent_permissions ALTER COLUMN permission_file SET NOT NULL;")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("agent_permissions")}

    if "permissions" not in columns:
        op.execute("ALTER TABLE agent_permissions ADD COLUMN IF NOT EXISTS permissions JSONB DEFAULT '{}'::jsonb;")

    if "permission_file" in columns:
        op.execute("ALTER TABLE agent_permissions DROP COLUMN IF EXISTS permission_file;")
