import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.auth.utils import create_access_token
from app.database import get_db
from app.main import app


class FakeResponse:
    def __init__(self, data: Any):
        self.data = data


class FakeTable:
    def __init__(self, table_name: str, db: "FakeDB"):
        self.table_name = table_name
        self.db = db
        self._filters: list[tuple[str, Any]] = []
        self._single = False
        self._insert_payload: dict[str, Any] | None = None
        self._update_payload: dict[str, Any] | None = None
        self._is_delete = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column: str, value: Any):
        self._filters.append((column, value))
        return self

    def limit(self, _value: int):
        return self

    def single(self):
        self._single = True
        return self

    def range(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def insert(self, payload: dict[str, Any]):
        self._insert_payload = payload
        return self

    def update(self, payload: dict[str, Any]):
        self._update_payload = payload
        return self

    def delete(self):
        self._is_delete = True
        return self

    def execute(self):
        rows = self.db.tables[self.table_name]

        def matches(row: dict[str, Any]) -> bool:
            return all(str(row.get(col)) == str(val) for col, val in self._filters)

        if self._insert_payload is not None:
            row = self._insert_payload.copy()
            row.setdefault("id", str(uuid4()))
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            row.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
            self.db.tables[self.table_name].append(row)
            return FakeResponse([row.copy()])

        if self._update_payload is not None:
            updated: list[dict[str, Any]] = []
            for row in rows:
                if matches(row):
                    row.update(self._update_payload)
                    row["updated_at"] = datetime.now(timezone.utc).isoformat()
                    updated.append(row.copy())
            return FakeResponse(updated)

        if self._is_delete:
            deleted = [row.copy() for row in rows if matches(row)]
            self.db.tables[self.table_name] = [row for row in rows if not matches(row)]
            return FakeResponse(deleted)

        filtered = [row.copy() for row in rows if matches(row)]
        if self._single:
            return FakeResponse(filtered[0] if filtered else None)

        return FakeResponse(filtered)


class FakeDB:
    def __init__(self):
        now = datetime.now(timezone.utc).isoformat()

        self.admin_id = str(uuid4())
        self.manager_id = str(uuid4())
        self.rep_id = str(uuid4())
        self.customer_id = str(uuid4())
        self.ticket_id = str(uuid4())

        self.tables: dict[str, list[dict[str, Any]]] = {
            "agents": [
                {
                    "id": self.admin_id,
                    "email": "admin@example.com",
                    "full_name": "Admin User",
                    "role": "admin",
                    "is_active": True,
                    "password_hash": "hashed::x",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": self.manager_id,
                    "email": "manager@example.com",
                    "full_name": "Manager User",
                    "role": "sales_manager",
                    "is_active": True,
                    "password_hash": "hashed::x",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": self.rep_id,
                    "email": "rep@example.com",
                    "full_name": "Rep User",
                    "role": "sales_rep",
                    "is_active": True,
                    "password_hash": "hashed::x",
                    "created_at": now,
                    "updated_at": now,
                },
            ],
            "customers": [
                {
                    "id": self.customer_id,
                    "email": "customer@example.com",
                    "full_name": "Customer One",
                    "phone": None,
                    "company": None,
                    "status": "active",
                    "notes": None,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
            "tickets": [
                {
                    "id": self.ticket_id,
                    "customer_id": self.customer_id,
                    "subject": "Need support",
                    "description": "Please help",
                    "status": "open",
                    "priority": "medium",
                    "category": None,
                    "assigned_to": None,
                    "ai_summary": None,
                    "ai_sentiment": None,
                    "ai_suggested_response": None,
                    "created_at": now,
                    "updated_at": now,
                    "resolved_at": None,
                }
            ],
            "ticket_messages": [],
        }

    def table(self, table_name: str) -> FakeTable:
        return FakeTable(table_name, self)


def _token_for(user_id: str) -> str:
    return create_access_token({"sub": user_id})


def _client_with_fake_db(monkeypatch) -> tuple[TestClient, FakeDB]:
    fake_db = FakeDB()
    monkeypatch.setattr("app.routers.users.hash_password", lambda password: f"hashed::{password}")
    app.dependency_overrides[get_db] = lambda: fake_db
    return TestClient(app), fake_db


def test_day2_rbac_permissions_and_user_crud(monkeypatch):
    client, fake_db = _client_with_fake_db(monkeypatch)

    admin_headers = {"Authorization": f"Bearer {_token_for(fake_db.admin_id)}"}
    manager_headers = {"Authorization": f"Bearer {_token_for(fake_db.manager_id)}"}
    rep_headers = {"Authorization": f"Bearer {_token_for(fake_db.rep_id)}"}

    # /users list should be admin-only.
    rep_users_res = client.get("/api/users/", headers=rep_headers)
    assert rep_users_res.status_code == 403

    admin_users_res = client.get("/api/users/", headers=admin_headers)
    assert admin_users_res.status_code == 200
    assert len(admin_users_res.json()) == 3

    # Admin user creation.
    create_user_res = client.post(
        "/api/users/",
        headers=admin_headers,
        json={
            "email": "new.rep@example.com",
            "full_name": "New Rep",
            "role": "sales_rep",
            "password": "new-password-123",
        },
    )
    assert create_user_res.status_code == 201

    # Customer deletion should be admin-only.
    rep_delete_customer = client.delete(f"/api/customers/{fake_db.customer_id}", headers=rep_headers)
    assert rep_delete_customer.status_code == 403

    admin_delete_customer = client.delete(f"/api/customers/{fake_db.customer_id}", headers=admin_headers)
    assert admin_delete_customer.status_code == 204

    # Ticket assignment should be sales_manager/admin only.
    rep_assign = client.patch(
        f"/api/tickets/{fake_db.ticket_id}",
        headers=rep_headers,
        json={"assigned_to": fake_db.rep_id},
    )
    assert rep_assign.status_code == 403

    manager_assign = client.patch(
        f"/api/tickets/{fake_db.ticket_id}",
        headers=manager_headers,
        json={"assigned_to": fake_db.manager_id},
    )
    assert manager_assign.status_code == 200


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
