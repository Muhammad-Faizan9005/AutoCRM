from __future__ import annotations

from typing import Dict
from uuid import UUID

from pydantic import BaseModel


class PermissionSet(BaseModel):
    user_id: UUID
    permissions: Dict[str, bool]


class PermissionUpdate(BaseModel):
    permissions: Dict[str, bool]
