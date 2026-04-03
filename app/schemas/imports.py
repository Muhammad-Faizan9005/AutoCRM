from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ImportFailure(BaseModel):
    row_number: int
    reason: str


class ImportResult(BaseModel):
    entity: Literal["customers", "tickets"]
    file_name: str
    total_rows: int
    successful_rows: int
    created_count: int
    updated_count: int
    failed_count: int
    failures: list[ImportFailure]

    model_config = ConfigDict(from_attributes=True)
