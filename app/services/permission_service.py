from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from supabase import Client

from app.config import settings
from app.repositories.permission_repository import PermissionRepository


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


def _normalize_role(role: str | None) -> str:
    if not role:
        return ""
    return role.strip().lower().replace("-", "_").replace(" ", "_")


def is_admin_user(user: dict[str, Any]) -> bool:
    if bool(user.get("is_admin")) or bool(user.get("is_superuser")):
        return True

    role = _normalize_role(str(user.get("role") or ""))
    return role in ADMIN_ROLE_ALIASES


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return bool(value)


def sanitize_permissions_map(permissions: dict[str, Any] | None) -> dict[str, bool]:
    if not permissions:
        return {}

    sanitized: dict[str, bool] = {}
    for key, value in permissions.items():
        if key in ALL_PERMISSIONS:
            sanitized[key] = _coerce_bool(value)
    return sanitized


def _role_defaults(role: str | None) -> dict[str, bool]:
    normalized = _normalize_role(role)

    sales_manager_defaults = {key: True for key in CRM_CORE_PERMISSIONS}
    sales_manager_defaults.update({
        "import_data": True,
        "admin_panel": False,
        "admin_users": True,
        "admin_permissions": True,
    })

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


def build_effective_permissions(
    user: dict[str, Any], overrides: dict[str, Any] | None
) -> dict[str, bool]:
    permissions = _role_defaults(user.get("role"))
    sanitized_overrides = sanitize_permissions_map(overrides)
    permissions.update(sanitized_overrides)

    if is_admin_user(user):
        for key in ADMIN_PERMISSIONS:
            permissions[key] = True
        permissions["import_data"] = True

    return permissions


class PermissionService:
    def __init__(self, db: Client):
        self.repository = PermissionRepository(db)
        self.storage_dir = self._resolve_storage_dir()

    @staticmethod
    def _resolve_storage_dir() -> Path:
        base_dir = Path(__file__).resolve().parents[2]
        configured = Path(settings.PERMISSIONS_STORAGE_DIR)
        if configured.is_absolute():
            return configured
        return base_dir / configured

    @staticmethod
    def _permission_file_name(user_id: str) -> str:
        return f"{user_id}.json"

    def _permission_file_path(self, file_name: str) -> Path:
        return self.storage_dir / file_name

    def _load_template_permissions(self) -> dict[str, bool]:
        template = self._load_permissions_file(TEMPLATE_FILE_NAME)
        if not isinstance(template, dict):
            normalized = {key: False for key in ALL_PERMISSIONS}
            self._write_permissions_file(TEMPLATE_FILE_NAME, normalized)
            return normalized

        normalized = {key: _coerce_bool(value) for key, value in template.items()}
        for key in ALL_PERMISSIONS:
            normalized.setdefault(key, False)
        if set(normalized.keys()) != set(template.keys()):
            self._write_permissions_file(TEMPLATE_FILE_NAME, normalized)
        return normalized

    def _load_permissions_file(self, file_name: str) -> dict[str, Any] | None:
        path = self._permission_file_path(file_name)
        if not path.exists():
            return None

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        if isinstance(raw, dict):
            return raw.get("permissions", raw)
        return None

    def _write_permissions_file(self, file_name: str, permissions: dict[str, bool]) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        path = self._permission_file_path(file_name)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(permissions, indent=2, sort_keys=True, ensure_ascii=True)
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(path)

    def _derive_permissions_for_file(
        self,
        user: dict[str, Any],
        overrides: dict[str, Any] | None,
    ) -> dict[str, bool]:
        permissions = self._load_template_permissions()
        permissions.update(_role_defaults(user.get("role")))
        permissions.update(sanitize_permissions_map(overrides))

        if is_admin_user(user):
            for key in ADMIN_PERMISSIONS:
                permissions[key] = True
            permissions["import_data"] = True

        return permissions

    async def get_effective_permissions(self, user: dict[str, Any]) -> dict[str, bool]:
        user_id = user.get("id")
        overrides: dict[str, Any] | None = None
        file_name: str | None = None
        if user_id:
            record = await self.repository.get_by_user_id(str(user_id))
            if record:
                file_name = record.get("permission_file")
                if file_name:
                    overrides = self._load_permissions_file(str(file_name))

        if overrides is not None:
            derived = self._derive_permissions_for_file(user, overrides)
            if file_name:
                self._write_permissions_file(str(file_name), derived)
            overrides = derived
        return build_effective_permissions(user, overrides)

    async def set_permissions(self, user: dict[str, Any], permissions: dict[str, Any]) -> dict[str, Any]:
        user_id = str(user.get("id")) if user.get("id") else ""
        if not user_id:
            raise ValueError("User id is required to set permissions")

        file_name = self._permission_file_name(user_id)
        derived = self._derive_permissions_for_file(user, permissions)
        self._write_permissions_file(file_name, derived)
        return await self.repository.upsert_permission_file(user_id, file_name)
