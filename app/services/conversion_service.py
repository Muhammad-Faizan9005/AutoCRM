"""
Conversion service for handling deal-to-customer and lead-to-deal conversions.

Implements the CRM workflow:
- Lead → Deal: Manual conversion, creates deal record
- Deal → Customer: Automatic on Won status, creates customer record
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from supabase import Client

from app.database import run_db_operation
from app.exceptions.custom_exceptions import DatabaseError, ResourceNotFoundError
from app.repositories.customer_repository import CustomerRepository
from app.repositories.deal_repository import DealRepository
from app.repositories.lead_repository import LeadRepository


class ConversionService:
    """Handles conversions between lead, deal, and customer entities."""

    def __init__(self, db: Client):
        self.db = db
        self.lead_repository = LeadRepository(db)
        self.deal_repository = DealRepository(db)
        self.customer_repository = CustomerRepository(db)

    async def convert_lead_to_deal(
        self,
        *,
        lead_id: str,
        stage: str = "qualified",
        value: float | None = None,
        currency: str = "USD",
        expected_close_at: datetime | None = None,
        owner_id: str | None = None,
        organization_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Convert a lead to a deal.

        Following the reference CRM pattern:
        1. Verify lead exists
        2. Create a deal linked to the lead
        3. Mark lead as converted and set status to "qualified"

        Args:
            lead_id: UUID of the lead to convert
            stage: Deal stage (default: "qualified")
            value: Deal value
            currency: Currency (default: "USD")
            expected_close_at: Expected close date
            owner_id: Deal owner
            organization_id: Deal organization

        Returns:
            Created deal dict

        Raises:
            NotFoundError: If lead not found
            DatabaseError: If database operation fails
        """
        # Verify lead exists
        lead = await self.lead_repository.get_by_id(lead_id)
        if not lead:
            raise ResourceNotFoundError(resource="Lead", resource_id=lead_id)

        # Create deal
        deal_data = {
            "lead_id": str(lead_id),
            "stage": stage,
            "status": "qualified",  # Always set to qualified when converting
            "value": value,
            "currency": currency,
            "expected_close_at": expected_close_at,
            "owner_id": owner_id or lead.get("owner_id"),
            "organization_id": organization_id or lead.get("organization_id"),
        }

        created_deal = await self.deal_repository.create(deal_data)

        # Mark lead as converted and update status to "qualified"
        await self.lead_repository.update_by_id(
            lead_id,
            {
                "converted": True,
                "status": "qualified",
            },
        )

        return created_deal

    async def convert_deal_to_customer(
        self,
        *,
        deal_id: str,
    ) -> dict[str, Any]:
        """
        Convert a deal to a customer when deal status becomes "Won".

        Following the reference CRM pattern:
        - Triggered only when deal status = "Won"
        - Creates a customer record from deal and lead data
        - Links customer back to deal

        Args:
            deal_id: UUID of the deal to convert

        Returns:
            Created customer dict

        Raises:
            NotFoundError: If deal not found
            ValueError: If deal status is not "Won"
            DatabaseError: If database operation fails
        """
        # Verify deal exists
        deal = await self.deal_repository.get_by_id(deal_id)
        if not deal:
            raise ResourceNotFoundError(resource="Deal", resource_id=deal_id)

        # Verify deal status is "Won"
        if deal.get("status") != "won":
            raise ValueError(f"Deal status must be 'won' to convert to customer. Current status: {deal.get('status')}")

        # If already converted, return existing customer
        if deal.get("customer_id"):
            customer = await self.customer_repository.get_by_id(deal["customer_id"])
            if customer:
                return customer

        # Get associated lead for details
        lead_id = deal.get("lead_id")
        lead = None
        if lead_id:
            lead = await self.lead_repository.get_by_id(lead_id)

        # Prepare customer data
        # Email is required by CustomerCreate schema, use a placeholder if not available
        email = (lead.get("email") if lead else None) or f"customer_{deal_id[:8]}@example.com"
        customer_data = {
            "full_name": lead.get("name") if lead else deal.get("stage"),
            "email": email,
            "phone": lead.get("phone") if lead else None,
            "company": lead.get("company") if lead else None,
            "status": "active",
            "notes": f"Converted from deal {deal_id}",
        }

        # Remove None values
        customer_data = {k: v for k, v in customer_data.items() if v is not None}

        # Create customer
        created_customer = await self.customer_repository.create(customer_data)

        # Link customer to deal
        await self.deal_repository.update_by_id(
            deal_id,
            {
                "customer_id": str(created_customer["id"]),
                "closed_at": datetime.utcnow(),
            },
        )

        return created_customer

    async def update_deal_status(
        self,
        *,
        deal_id: str,
        new_status: str,
    ) -> dict[str, Any]:
        """
        Update deal status and trigger conversion if status becomes "Won".

        Args:
            deal_id: UUID of the deal
            new_status: New status value (e.g., "won", "lost", "qualified")

        Returns:
            Updated deal dict

        Raises:
            NotFoundError: If deal not found
            DatabaseError: If database operation fails
        """
        # Update deal status
        update_data = {"status": new_status.lower()}

        # Auto-set closed_at for terminal statuses
        if new_status.lower() in ("won", "lost"):
            update_data["closed_at"] = datetime.utcnow()

        updated_deal = await self.deal_repository.update_by_id(deal_id, update_data)

        # If status changed to "won", convert to customer
        if new_status.lower() == "won":
            try:
                await self.convert_deal_to_customer(deal_id=deal_id)
            except ValueError:
                # Customer already created, ignore
                pass
            except Exception as exc:
                # Log but don't fail the update
                print(f"Warning: Failed to convert deal to customer: {exc}")

        return updated_deal
