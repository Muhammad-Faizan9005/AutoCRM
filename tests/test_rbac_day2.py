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
        self.other_rep_id = str(uuid4())
        self.team_id = str(uuid4())
        self.customer_id = str(uuid4())
        self.linked_customer_id = str(uuid4())
        self.other_customer_id = str(uuid4())
        self.unassigned_customer_id = str(uuid4())
        self.organization_id = str(uuid4())
        self.linked_organization_id = str(uuid4())
        self.other_organization_id = str(uuid4())
        self.unassigned_organization_id = str(uuid4())
        self.lead_id = str(uuid4())
        self.deal_id = str(uuid4())
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
                {
                    "id": self.other_rep_id,
                    "email": "other.rep@example.com",
                    "full_name": "Other Rep",
                    "role": "sales_rep",
                    "is_active": True,
                    "password_hash": "hashed::x",
                    "created_at": now,
                    "updated_at": now,
                },
            ],
            "teams": [
                {
                    "id": self.team_id,
                    "name": "Manager Team",
                    "manager_id": self.manager_id,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
            "team_members": [
                {
                    "team_id": self.team_id,
                    "agent_id": self.rep_id,
                    "joined_at": now,
                }
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
                    "owner_id": self.rep_id,
                    "team_id": self.team_id,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": self.other_customer_id,
                    "email": "other.customer@example.com",
                    "full_name": "Other Customer",
                    "phone": None,
                    "company": None,
                    "status": "active",
                    "notes": None,
                    "owner_id": self.other_rep_id,
                    "team_id": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": self.linked_customer_id,
                    "email": "linked.customer@example.com",
                    "full_name": "Linked Customer",
                    "phone": None,
                    "company": "Linked Org",
                    "status": "active",
                    "notes": None,
                    "owner_id": None,
                    "team_id": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": self.unassigned_customer_id,
                    "email": "unassigned.customer@example.com",
                    "full_name": "Unassigned Customer",
                    "phone": None,
                    "company": None,
                    "status": "active",
                    "notes": None,
                    "owner_id": None,
                    "team_id": None,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
            "organizations": [
                {
                    "id": self.organization_id,
                    "name": "Rep Org",
                    "website": None,
                    "industry": "software",
                    "revenue": None,
                    "address": None,
                    "phone": None,
                    "owner_id": self.rep_id,
                    "team_id": self.team_id,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": self.other_organization_id,
                    "name": "Other Org",
                    "website": None,
                    "industry": "finance",
                    "revenue": None,
                    "address": None,
                    "phone": None,
                    "owner_id": self.other_rep_id,
                    "team_id": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": self.linked_organization_id,
                    "name": "Linked Org",
                    "website": None,
                    "industry": "healthcare",
                    "revenue": None,
                    "address": None,
                    "phone": None,
                    "owner_id": None,
                    "team_id": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": self.unassigned_organization_id,
                    "name": "Unassigned Org",
                    "website": None,
                    "industry": "retail",
                    "revenue": None,
                    "address": None,
                    "phone": None,
                    "owner_id": None,
                    "team_id": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
            "leads": [
                {
                    "id": self.lead_id,
                    "owner_id": self.rep_id,
                    "organization_id": self.linked_organization_id,
                    "name": "Linked Lead",
                    "email": "linked@example.com",
                    "phone": None,
                    "company": "Linked Org",
                    "source": "manual",
                    "status": "new",
                    "score": None,
                    "score_reason": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
            "deals": [
                {
                    "id": self.deal_id,
                    "lead_id": self.lead_id,
                    "owner_id": self.rep_id,
                    "organization_id": self.linked_organization_id,
                    "customer_id": self.linked_customer_id,
                    "stage": "closing",
                    "status": "won",
                    "deal_type": "new_business",
                    "value": 1000,
                    "currency": "USD",
                    "expected_close_at": None,
                    "closed_at": now,
                    "lost_reason": None,
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
            "agent_permissions": [],
        }

    def table(self, table_name: str) -> FakeTable:
        return FakeTable(table_name, self)


def _token_for(user_id: str) -> str:
    return create_access_token({"sub": user_id})


def _client_with_fake_db(monkeypatch) -> tuple[TestClient, FakeDB]:
    fake_db = FakeDB()

    async def _fake_calculate_lead_score(*_args, **_kwargs):
        return None

    async def _fake_get_agent_name(*_args, **_kwargs):
        return "Test User"

    async def _fake_create_notification(*_args, **_kwargs):
        return {"id": str(uuid4())}

    async def _fake_get_recipient_email(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.registration_service.hash_password", lambda password: f"hashed::{password}")
    monkeypatch.setattr("app.routers.leads.calculate_lead_score", _fake_calculate_lead_score)
    monkeypatch.setattr("app.services.notification_service.NotificationService.get_agent_name", _fake_get_agent_name)
    monkeypatch.setattr("app.services.notification_service.NotificationService.create_notification", _fake_create_notification)
    monkeypatch.setattr("app.services.email_service.MailjetEmailService.get_recipient_email", _fake_get_recipient_email)
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
    assert len(admin_users_res.json()) == 4

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


def test_customer_and_organization_record_visibility(monkeypatch):
    client, fake_db = _client_with_fake_db(monkeypatch)

    admin_headers = {"Authorization": f"Bearer {_token_for(fake_db.admin_id)}"}
    manager_headers = {"Authorization": f"Bearer {_token_for(fake_db.manager_id)}"}
    rep_headers = {"Authorization": f"Bearer {_token_for(fake_db.rep_id)}"}

    rep_customers = client.get("/api/customers/", headers=rep_headers)
    assert rep_customers.status_code == 200
    assert {row["id"] for row in rep_customers.json()} == {
        fake_db.customer_id,
        fake_db.linked_customer_id,
    }

    manager_customers = client.get("/api/customers/", headers=manager_headers)
    assert manager_customers.status_code == 200
    assert {row["id"] for row in manager_customers.json()} == {
        fake_db.customer_id,
        fake_db.linked_customer_id,
    }

    admin_customers = client.get("/api/customers/", headers=admin_headers)
    assert admin_customers.status_code == 200
    assert {row["id"] for row in admin_customers.json()} == {
        fake_db.customer_id,
        fake_db.linked_customer_id,
        fake_db.other_customer_id,
        fake_db.unassigned_customer_id,
    }

    linked_customer = client.get(f"/api/customers/{fake_db.linked_customer_id}", headers=rep_headers)
    assert linked_customer.status_code == 200

    forbidden_customer = client.get(f"/api/customers/{fake_db.other_customer_id}", headers=rep_headers)
    assert forbidden_customer.status_code == 403

    manager_unassigned_customer = client.get(f"/api/customers/{fake_db.unassigned_customer_id}", headers=manager_headers)
    assert manager_unassigned_customer.status_code == 403

    rep_organizations = client.get("/api/organizations/", headers=rep_headers)
    assert rep_organizations.status_code == 200
    assert {row["id"] for row in rep_organizations.json()} == {
        fake_db.organization_id,
        fake_db.linked_organization_id,
    }

    manager_organizations = client.get("/api/organizations/", headers=manager_headers)
    assert manager_organizations.status_code == 200
    assert {row["id"] for row in manager_organizations.json()} == {
        fake_db.organization_id,
        fake_db.linked_organization_id,
    }

    linked_organization = client.get(f"/api/organizations/{fake_db.linked_organization_id}", headers=rep_headers)
    assert linked_organization.status_code == 200

    forbidden_organization = client.get(f"/api/organizations/{fake_db.other_organization_id}", headers=rep_headers)
    assert forbidden_organization.status_code == 403

    manager_unassigned_organization = client.get(
        f"/api/organizations/{fake_db.unassigned_organization_id}",
        headers=manager_headers,
    )
    assert manager_unassigned_organization.status_code == 403


def test_admin_allocates_leads_to_managers_then_manager_assigns_team(monkeypatch):
    client, fake_db = _client_with_fake_db(monkeypatch)

    admin_headers = {"Authorization": f"Bearer {_token_for(fake_db.admin_id)}"}
    manager_headers = {"Authorization": f"Bearer {_token_for(fake_db.manager_id)}"}

    admin_targets = client.get("/api/leads/assignment-reps", headers=admin_headers)
    assert admin_targets.status_code == 200
    assert {row["id"] for row in admin_targets.json()} == {fake_db.manager_id}

    manager_targets = client.get("/api/leads/assignment-reps", headers=manager_headers)
    assert manager_targets.status_code == 200
    assert {row["id"] for row in manager_targets.json()} == {fake_db.rep_id}

    admin_to_rep = client.patch(
        f"/api/leads/{fake_db.lead_id}",
        headers=admin_headers,
        json={"owner_id": fake_db.rep_id},
    )
    assert admin_to_rep.status_code == 403

    admin_to_manager = client.patch(
        f"/api/leads/{fake_db.lead_id}",
        headers=admin_headers,
        json={"owner_id": fake_db.manager_id},
    )
    assert admin_to_manager.status_code == 200
    assert admin_to_manager.json()["owner_id"] == fake_db.manager_id

    manager_leads = client.get("/api/leads/", headers=manager_headers)
    assert manager_leads.status_code == 200
    assert fake_db.lead_id in {row["id"] for row in manager_leads.json()}

    manager_to_rep = client.patch(
        f"/api/leads/{fake_db.lead_id}",
        headers=manager_headers,
        json={"owner_id": fake_db.rep_id},
    )
    assert manager_to_rep.status_code == 200
    assert manager_to_rep.json()["owner_id"] == fake_db.rep_id


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
