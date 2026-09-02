from __future__ import annotations

import pytest

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.billing import (
    BillingPermissionError,
    cancel_billing_arrangement,
    compute_engagement_profitability,
    create_billing_arrangement,
    create_engagement_cost,
    create_invoice,
    delete_engagement_cost,
    record_payment,
    update_invoice_status,
    void_payment,
)
from app.services.client_delivery import onboard_client_from_lead
from app.services.lead_pipeline_workflow import change_pipeline_stage
from app.services.leads import create_lead
from app.services.relationship_manager import assign_relationship_manager
from app.services.team_users import create_relationship_manager, set_workspace_membership


OWNER = {"id": 1, "username": "mark", "role": "owner"}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def billing_database(tmp_path, monkeypatch):
    path = tmp_path / "billing.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        junmar = create_relationship_manager(
            db,
            username="junmar",
            display_name="Junmar",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        lead = create_lead(
            db,
            company="Billing Co",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="Referral",
            source_url="https://example.com/billing",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="meeting",
            priority="medium",
            next_action="Close the deal.",
            notes="",
            organization_id=organization_id,
        ).lead
        assign_relationship_manager(
            db,
            lead["id"],
            actor=OWNER,
            relationship_manager_user_id=junmar["id"],
            organization_id=organization_id,
        )
        change_pipeline_stage(
            db, lead["id"], actor=OWNER, pipeline_status="proposal",
            organization_id=organization_id,
        )
        change_pipeline_stage(
            db, lead["id"], actor=OWNER, pipeline_status="won",
            organization_id=organization_id,
        )
        client = onboard_client_from_lead(
            db,
            lead["id"],
            actor=OWNER,
            organization_id=organization_id,
            engagement_title="Delivery engagement",
        )
        engagement = db.execute(
            "SELECT * FROM client_engagements WHERE client_id = ?",
            (client["id"],),
        ).fetchone()

    return {
        "organization_id": organization_id,
        "engagement_id": engagement["id"],
        "junmar": dict(junmar),
    }


def test_owner_can_create_billing_arrangement(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]

    with database.get_db() as db:
        arrangement = create_billing_arrangement(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            billing_model="retainer",
            amount_minor_units=50_000_00,
            start_date="2026-09-01",
            commission_rate_basis_points=1000,
        )

    assert arrangement["billing_model"] == "retainer"
    assert arrangement["amount_minor_units"] == 50_000_00
    assert arrangement["status"] == "active"


def test_relationship_manager_cannot_touch_billing(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]
    junmar = billing_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        with pytest.raises(BillingPermissionError):
            create_billing_arrangement(
                db,
                engagement_id,
                actor=junmar_actor,
                organization_id=organization_id,
                billing_model="retainer",
                amount_minor_units=1_000_00,
                start_date="2026-09-01",
            )


def test_workspace_owner_manager_still_cannot_view_finance(billing_database):
    """Confirmed design: financial data is the literal global Owner only."""
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]
    junmar = billing_database["junmar"]

    with database.get_db() as db:
        set_workspace_membership(
            db,
            target_user_id=junmar["id"],
            acting_user_id=OWNER["id"],
            workspace_slug="mark-agency",
            membership_role="workspace_owner",
            active=True,
        )
        junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

        with pytest.raises(BillingPermissionError):
            create_billing_arrangement(
                db,
                engagement_id,
                actor=junmar_actor,
                organization_id=organization_id,
                billing_model="retainer",
                amount_minor_units=1_000_00,
                start_date="2026-09-01",
            )


def test_cancel_billing_arrangement(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]

    with database.get_db() as db:
        arrangement = create_billing_arrangement(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            billing_model="retainer",
            amount_minor_units=1_000_00,
            start_date="2026-09-01",
        )
        cancelled = cancel_billing_arrangement(
            db,
            arrangement["id"],
            actor=OWNER,
            organization_id=organization_id,
            cancellation_date="2026-10-01",
            expected_row_version=arrangement["row_version"],
        )

    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellation_date"] == "2026-10-01"


def test_invoice_reference_must_be_unique_per_workspace(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]

    with database.get_db() as db:
        create_invoice(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            invoice_reference="INV-2026-001",
            invoice_date="2026-09-01",
            amount_minor_units=50_000_00,
        )

        with pytest.raises(ValueError, match="already exists"):
            create_invoice(
                db,
                engagement_id,
                actor=OWNER,
                organization_id=organization_id,
                invoice_reference="INV-2026-001",
                invoice_date="2026-09-15",
                amount_minor_units=10_000_00,
            )


def test_invoice_status_is_explicit_not_derived(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]

    with database.get_db() as db:
        invoice = create_invoice(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            invoice_reference="INV-2026-002",
            invoice_date="2026-09-01",
            amount_minor_units=50_000_00,
        )
        assert invoice["status"] == "draft"

        # Recording a payment for the full amount must NOT auto-flip status.
        record_payment(
            db,
            invoice["id"],
            actor=OWNER,
            organization_id=organization_id,
            amount_minor_units=50_000_00,
            payment_date="2026-09-05",
        )
        reloaded = db.execute(
            "SELECT status FROM invoices WHERE id = ?", (invoice["id"],)
        ).fetchone()
        assert reloaded["status"] == "draft"

        updated = update_invoice_status(
            db,
            invoice["id"],
            actor=OWNER,
            organization_id=organization_id,
            status="paid",
            expected_row_version=invoice["row_version"],
        )
        assert updated["status"] == "paid"


def test_profitability_is_computed_from_ledger(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]

    with database.get_db() as db:
        create_billing_arrangement(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            billing_model="retainer",
            amount_minor_units=50_000_00,
            start_date="2026-09-01",
            commission_rate_basis_points=1000,
        )
        invoice = create_invoice(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            invoice_reference="INV-2026-003",
            invoice_date="2026-09-01",
            amount_minor_units=50_000_00,
        )
        record_payment(
            db,
            invoice["id"],
            actor=OWNER,
            organization_id=organization_id,
            amount_minor_units=50_000_00,
            payment_date="2026-09-05",
        )
        create_engagement_cost(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            cost_type="contractor_cost",
            description="Freelance dashboard build",
            amount_minor_units=10_000_00,
            incurred_date="2026-09-03",
        )

        profitability = compute_engagement_profitability(
            db, engagement_id, actor=OWNER, organization_id=organization_id
        )

    assert profitability.collected_revenue_minor_units == 50_000_00
    assert profitability.total_costs_minor_units == 10_000_00
    assert profitability.gross_profit_minor_units == 40_000_00
    assert profitability.margin == pytest.approx(0.8)
    assert profitability.commission_minor_units == 5_000_00


def test_voided_payment_excluded_from_revenue(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]

    with database.get_db() as db:
        invoice = create_invoice(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            invoice_reference="INV-2026-004",
            invoice_date="2026-09-01",
            amount_minor_units=20_000_00,
        )
        payment = record_payment(
            db,
            invoice["id"],
            actor=OWNER,
            organization_id=organization_id,
            amount_minor_units=20_000_00,
            payment_date="2026-09-05",
        )

        before = compute_engagement_profitability(
            db, engagement_id, actor=OWNER, organization_id=organization_id
        )
        assert before.collected_revenue_minor_units == 20_000_00

        voided = void_payment(
            db,
            payment["id"],
            actor=OWNER,
            organization_id=organization_id,
            void_reason="Entered against the wrong invoice.",
        )
        assert voided["voided_at"] is not None

        after = compute_engagement_profitability(
            db, engagement_id, actor=OWNER, organization_id=organization_id
        )

    assert after.collected_revenue_minor_units == 0


def test_payment_cannot_be_voided_twice(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]

    with database.get_db() as db:
        invoice = create_invoice(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            invoice_reference="INV-2026-005",
            invoice_date="2026-09-01",
            amount_minor_units=5_000_00,
        )
        payment = record_payment(
            db,
            invoice["id"],
            actor=OWNER,
            organization_id=organization_id,
            amount_minor_units=5_000_00,
            payment_date="2026-09-05",
        )
        void_payment(
            db,
            payment["id"],
            actor=OWNER,
            organization_id=organization_id,
            void_reason="Duplicate entry.",
        )

        with pytest.raises(ValueError, match="already voided"):
            void_payment(
                db,
                payment["id"],
                actor=OWNER,
                organization_id=organization_id,
                void_reason="Trying again.",
            )


def test_deleted_cost_excluded_from_profitability(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]

    with database.get_db() as db:
        cost = create_engagement_cost(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            cost_type="pass_through_expense",
            description="Third-party API credits",
            amount_minor_units=2_000_00,
            incurred_date="2026-09-02",
        )

        before = compute_engagement_profitability(
            db, engagement_id, actor=OWNER, organization_id=organization_id
        )
        assert before.total_costs_minor_units == 2_000_00

        delete_engagement_cost(
            db, cost["id"], actor=OWNER, organization_id=organization_id
        )

        after = compute_engagement_profitability(
            db, engagement_id, actor=OWNER, organization_id=organization_id
        )

    assert after.total_costs_minor_units == 0


def test_margin_is_none_without_revenue(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]

    with database.get_db() as db:
        profitability = compute_engagement_profitability(
            db, engagement_id, actor=OWNER, organization_id=organization_id
        )

    assert profitability.collected_revenue_minor_units == 0
    assert profitability.margin is None


def test_negative_payment_amount_is_rejected(billing_database):
    organization_id = billing_database["organization_id"]
    engagement_id = billing_database["engagement_id"]

    with database.get_db() as db:
        invoice = create_invoice(
            db,
            engagement_id,
            actor=OWNER,
            organization_id=organization_id,
            invoice_reference="INV-2026-006",
            invoice_date="2026-09-01",
            amount_minor_units=1_000_00,
        )
        with pytest.raises(ValueError, match="positive amount"):
            record_payment(
                db,
                invoice["id"],
                actor=OWNER,
                organization_id=organization_id,
                amount_minor_units=-500,
                payment_date="2026-09-05",
            )
