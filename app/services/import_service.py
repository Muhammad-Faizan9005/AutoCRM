from __future__ import annotations

import csv
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from supabase import Client

from app.repositories.customer_repository import CustomerRepository
from app.repositories.ticket_repository import TicketRepository
from app.schemas.customer import CustomerCreate
from app.schemas.imports import ImportFailure, ImportResult
from app.schemas.ticket import TicketCreate


try:
    from openpyxl import load_workbook
except Exception:  # pragma: no cover - validated during runtime if dependency is missing
    load_workbook = None


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xlsm"}


@dataclass
class ParsedRow:
    row_number: int
    values: dict[str, Any]


def _normalize_header(value: Any) -> str:
    if value is None:
        return ""
    normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    return normalized


def _normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_csv(file_bytes: bytes) -> list[ParsedRow]:
    last_error: Exception | None = None
    text: str | None = None

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError as exc:
            last_error = exc

    if text is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to decode CSV file") from last_error

    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file is missing header row")

    normalized_headers = [_normalize_header(h) for h in reader.fieldnames]
    if any(not h for h in normalized_headers):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV header contains empty column name")

    parsed_rows: list[ParsedRow] = []
    for row_index, row in enumerate(reader, start=2):
        normalized_row = {}
        for original_key, normalized_key in zip(reader.fieldnames, normalized_headers):
            normalized_row[normalized_key] = _normalize_cell(row.get(original_key))

        if all(not value for value in normalized_row.values()):
            continue

        parsed_rows.append(ParsedRow(row_number=row_index, values=normalized_row))

    return parsed_rows


def _parse_excel(file_bytes: bytes) -> list[ParsedRow]:
    if load_workbook is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Excel import support is unavailable. Install openpyxl.",
        )

    workbook = load_workbook(filename=BytesIO(file_bytes), read_only=True, data_only=True)
    sheet = workbook.active
    iterator = sheet.iter_rows(values_only=True)
    header_row = next(iterator, None)

    if not header_row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Excel file is empty")

    normalized_headers = [_normalize_header(value) for value in header_row]
    if not any(normalized_headers):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Excel header row is empty")
    if any(not h for h in normalized_headers):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Excel header contains empty column name")

    parsed_rows: list[ParsedRow] = []
    for row_index, values in enumerate(iterator, start=2):
        row_dict: dict[str, str] = {}
        for column_index, header in enumerate(normalized_headers):
            cell_value = values[column_index] if column_index < len(values) else None
            row_dict[header] = _normalize_cell(cell_value)

        if all(not value for value in row_dict.values()):
            continue

        parsed_rows.append(ParsedRow(row_number=row_index, values=row_dict))

    return parsed_rows


def _parse_rows(file_name: str, file_bytes: bytes) -> list[ParsedRow]:
    suffix = Path(file_name or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Use CSV or Excel (.xlsx/.xlsm).",
        )

    if suffix == ".csv":
        return _parse_csv(file_bytes)
    return _parse_excel(file_bytes)


class ImportService:
    def __init__(self, db: Client):
        self.customer_repository = CustomerRepository(db)
        self.ticket_repository = TicketRepository(db)

    async def import_customers(self, *, file_name: str, file_bytes: bytes) -> ImportResult:
        parsed_rows = _parse_rows(file_name=file_name, file_bytes=file_bytes)

        created_count = 0
        updated_count = 0
        failures: list[ImportFailure] = []

        for parsed_row in parsed_rows:
            try:
                payload = {
                    "email": parsed_row.values.get("email", ""),
                    "full_name": parsed_row.values.get("full_name", ""),
                    "phone": parsed_row.values.get("phone") or None,
                    "company": parsed_row.values.get("company") or None,
                    "status": (parsed_row.values.get("status") or "active").lower(),
                    "notes": parsed_row.values.get("notes") or None,
                }
                model = CustomerCreate(**payload)

                existing_customer = await self.customer_repository.find_one(filters={"email": str(model.email)})
                if existing_customer:
                    update_payload = model.model_dump(exclude_none=True)
                    await self.customer_repository.update_by_id(existing_customer["id"], update_payload)
                    updated_count += 1
                else:
                    await self.customer_repository.create(model.model_dump(exclude_none=True))
                    created_count += 1
            except Exception as exc:
                failures.append(ImportFailure(row_number=parsed_row.row_number, reason=str(exc)))

        successful_rows = created_count + updated_count
        return ImportResult(
            entity="customers",
            file_name=file_name,
            total_rows=len(parsed_rows),
            successful_rows=successful_rows,
            created_count=created_count,
            updated_count=updated_count,
            failed_count=len(failures),
            failures=failures,
        )

    async def import_tickets(self, *, file_name: str, file_bytes: bytes) -> ImportResult:
        parsed_rows = _parse_rows(file_name=file_name, file_bytes=file_bytes)

        created_count = 0
        failures: list[ImportFailure] = []

        for parsed_row in parsed_rows:
            try:
                customer_id = parsed_row.values.get("customer_id") or None
                customer_email = parsed_row.values.get("customer_email") or None

                if not customer_id and customer_email:
                    customer = await self.customer_repository.find_one(filters={"email": customer_email})
                    if not customer:
                        raise ValueError(f"Customer not found for email: {customer_email}")
                    customer_id = customer["id"]

                if not customer_id:
                    raise ValueError("Either customer_id or customer_email is required")

                payload = {
                    "customer_id": str(customer_id),
                    "subject": parsed_row.values.get("subject", ""),
                    "description": parsed_row.values.get("description") or None,
                    "status": (parsed_row.values.get("status") or "open").lower(),
                    "priority": (parsed_row.values.get("priority") or "medium").lower(),
                    "category": parsed_row.values.get("category") or None,
                }
                model = TicketCreate(**payload)
                create_payload = model.model_dump()
                create_payload["customer_id"] = str(create_payload["customer_id"])

                created_ticket = await self.ticket_repository.create(create_payload)
                assigned_to = parsed_row.values.get("assigned_to") or None
                if assigned_to:
                    await self.ticket_repository.update_by_id(created_ticket["id"], {"assigned_to": assigned_to})

                created_count += 1
            except Exception as exc:
                failures.append(ImportFailure(row_number=parsed_row.row_number, reason=str(exc)))

        return ImportResult(
            entity="tickets",
            file_name=file_name,
            total_rows=len(parsed_rows),
            successful_rows=created_count,
            created_count=created_count,
            updated_count=0,
            failed_count=len(failures),
            failures=failures,
        )
