from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.db.billing import (
    BILLING_MODELS,
    BILLING_PERIODS,
    ENGAGEMENT_COST_TYPES,
    INVOICE_STATUSES,
)
from app.services.client_delivery import get_engagement
from app.services.lead_research_permissions import can_view_private_finance
from app.services.workspace_context import load_crm_actor_for_workspace


Record = Mapping[str, Any]

MAX_TEXT_LENGTH = 500
MAX_LONG_TEXT_LENGTH = 2_000


class BillingPermissionError(PermissionError):
    """Raised when a non-Owner actor attempts a financial-data action."""


@dataclass(frozen=True)
class EngagementProfitability:
    engagement_id: int
    collected_revenue_minor_units: int
    total_costs_minor_units: int
    gross_profit_minor_units: int
    margin: float | None
    commission_minor_units: int | None
    commission_rate_basis_points: int | None


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _required_text(value: Any, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = " ".join(value.strip().split())
    if not clean:
        raise ValueError(f"{field_name} is required.")
    if len(clean) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer.")
    return clean


def _optional_text(value: Any, field_name: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = " ".join(value.strip().split())
    if len(clean) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer.")
    return clean


def _required_date_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required.")
    return value.strip()


def _optional_date_text(value: Any, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    return value.strip()


def _required_amount(value: Any, field_name: str, *, allow_zero: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be a whole number of minor units.")
    if value < 0 or (not allow_zero and value <= 0):
        raise ValueError(f"{field_name} must be a positive amount.")
    return value


def _clean_currency(value: Any) -> str:
    clean = _optional_text(value, "Currency", 8)
    return clean.upper() or "PHP"


def _actor_for_workspace(db: sqlite3.Connection, actor: Record, organization_id: int) -> Record:
    try:
        return load_crm_actor_for_workspace(db, actor, organization_id)
    except PermissionError as exc:
        raise BillingPermissionError(
            "You are not allowed to access this CRM workspace."
        ) from exc


def _actor_id(actor: Record) -> int | None:
    value = actor.get("id") if hasattr(actor, "get") else None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _require_owner(db: sqlite3.Connection, actor: Record, organization_id: int) -> Record:
    actor = _actor_for_workspace(db, actor, organization_id)
    if not can_view_private_finance(actor):
        raise BillingPermissionError(
            "Financial data is Owner-only."
        )
    return actor


def _require_engagement(db: sqlite3.Connection, engagement_id: int, organization_id: int) -> dict[str, Any]:
    engagement = get_engagement(db, engagement_id, organization_id=organization_id)
    if engagement is None:
        raise ValueError("Engagement not found.")
    return engagement


# ---------------------------------------------------------------------------
# Billing arrangements
# ---------------------------------------------------------------------------


def get_billing_arrangement(
    db: sqlite3.Connection, arrangement_id: int, *, organization_id: int
) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT * FROM billing_arrangements WHERE id = ? AND organization_id = ?",
        (
            _positive_id(arrangement_id, "Billing arrangement ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchone()
    return dict(row) if row is not None else None


def list_billing_arrangements(
    db: sqlite3.Connection, engagement_id: int, *, organization_id: int
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT * FROM billing_arrangements
        WHERE engagement_id = ? AND organization_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (
            _positive_id(engagement_id, "Engagement ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def create_billing_arrangement(
    db: sqlite3.Connection,
    engagement_id: int,
    *,
    actor: Record,
    organization_id: int,
    billing_model: str,
    amount_minor_units: int,
    start_date: str,
    billing_period: str = "monthly",
    currency: str = "PHP",
    commission_recipient_user_id: int | None = None,
    commission_rate_basis_points: int | None = None,
    notes: str = "",
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _require_owner(db, actor, safe_organization_id)
    safe_engagement_id = _positive_id(engagement_id, "Engagement ID")
    _require_engagement(db, safe_engagement_id, safe_organization_id)

    clean_model = str(billing_model or "").strip().casefold()
    if clean_model not in BILLING_MODELS:
        raise ValueError("Unsupported billing model.")
    clean_period = str(billing_period or "").strip().casefold() or "monthly"
    if clean_period not in BILLING_PERIODS:
        raise ValueError("Unsupported billing period.")
    safe_amount = _required_amount(amount_minor_units, "Amount")
    clean_currency = _clean_currency(currency)
    safe_start_date = _required_date_text(start_date, "Start date")
    clean_notes = _optional_text(notes, "Notes", MAX_LONG_TEXT_LENGTH)

    safe_commission_rate = commission_rate_basis_points
    if safe_commission_rate is not None:
        if isinstance(safe_commission_rate, bool) or not isinstance(
            safe_commission_rate, int
        ):
            raise ValueError("Commission rate must be a whole number.")
        if not (0 <= safe_commission_rate <= 10_000):
            raise ValueError(
                "Commission rate must be between 0 and 10000 basis points."
            )

    safe_commission_recipient = commission_recipient_user_id
    if safe_commission_recipient is not None:
        row = db.execute(
            """
            SELECT users.id
            FROM users
            JOIN organization_memberships AS membership
              ON membership.user_id = users.id
             AND membership.organization_id = ?
            WHERE users.id = ? AND users.active = 1 AND membership.active = 1
            """,
            (safe_organization_id, safe_commission_recipient),
        ).fetchone()
        if row is None:
            raise ValueError(
                "Commission recipient must reference an active workspace user."
            )

    actor_id = _actor_id(actor)
    cursor = db.execute(
        """
        INSERT INTO billing_arrangements (
            organization_id, engagement_id, billing_model, billing_period,
            amount_minor_units, currency, commission_recipient_user_id,
            commission_rate_basis_points, start_date, notes,
            created_by_user_id, updated_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            safe_engagement_id,
            clean_model,
            clean_period,
            safe_amount,
            clean_currency,
            safe_commission_recipient,
            safe_commission_rate,
            safe_start_date,
            clean_notes,
            actor_id,
            actor_id,
        ),
    )
    return get_billing_arrangement(
        db, cursor.lastrowid, organization_id=safe_organization_id
    )


def cancel_billing_arrangement(
    db: sqlite3.Connection,
    arrangement_id: int,
    *,
    actor: Record,
    organization_id: int,
    cancellation_date: str,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    _require_owner(db, actor, safe_organization_id)

    current = get_billing_arrangement(
        db, arrangement_id, organization_id=safe_organization_id
    )
    if current is None:
        raise ValueError("Billing arrangement not found.")
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This billing arrangement changed in another session.")

    safe_cancellation_date = _required_date_text(cancellation_date, "Cancellation date")
    cursor = db.execute(
        """
        UPDATE billing_arrangements
        SET status = 'cancelled', cancellation_date = ?,
            row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND status = 'active'
          AND (? IS NULL OR row_version = ?)
        """,
        (
            safe_cancellation_date,
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This billing arrangement changed in another session.")
    return get_billing_arrangement(
        db, arrangement_id, organization_id=safe_organization_id
    )


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


def get_invoice(
    db: sqlite3.Connection, invoice_id: int, *, organization_id: int
) -> dict[str, Any] | None:
    row = db.execute(
        """
        SELECT * FROM invoices
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
        """,
        (
            _positive_id(invoice_id, "Invoice ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchone()
    return dict(row) if row is not None else None


def list_invoices_for_engagement(
    db: sqlite3.Connection, engagement_id: int, *, organization_id: int
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT * FROM invoices
        WHERE engagement_id = ? AND organization_id = ? AND deleted_at IS NULL
        ORDER BY invoice_date DESC, id DESC
        """,
        (
            _positive_id(engagement_id, "Engagement ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def create_invoice(
    db: sqlite3.Connection,
    engagement_id: int,
    *,
    actor: Record,
    organization_id: int,
    invoice_reference: str,
    invoice_date: str,
    amount_minor_units: int,
    currency: str = "PHP",
    billing_arrangement_id: int | None = None,
    due_date: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _require_owner(db, actor, safe_organization_id)
    safe_engagement_id = _positive_id(engagement_id, "Engagement ID")
    _require_engagement(db, safe_engagement_id, safe_organization_id)

    if billing_arrangement_id is not None:
        arrangement = get_billing_arrangement(
            db, billing_arrangement_id, organization_id=safe_organization_id
        )
        if arrangement is None or int(arrangement["engagement_id"]) != safe_engagement_id:
            raise ValueError("Billing arrangement not found for this engagement.")

    clean_reference = _required_text(
        invoice_reference, "Invoice reference", MAX_TEXT_LENGTH
    )
    safe_invoice_date = _required_date_text(invoice_date, "Invoice date")
    safe_amount = _required_amount(amount_minor_units, "Amount")
    clean_currency = _clean_currency(currency)
    safe_due_date = _optional_date_text(due_date, "Due date")
    safe_period_start = _optional_date_text(period_start, "Period start")
    safe_period_end = _optional_date_text(period_end, "Period end")
    clean_notes = _optional_text(notes, "Notes", MAX_LONG_TEXT_LENGTH)

    existing = db.execute(
        "SELECT 1 FROM invoices WHERE organization_id = ? AND invoice_reference = ?",
        (safe_organization_id, clean_reference),
    ).fetchone()
    if existing is not None:
        raise ValueError("An invoice with this reference already exists.")

    actor_id = _actor_id(actor)
    cursor = db.execute(
        """
        INSERT INTO invoices (
            organization_id, engagement_id, billing_arrangement_id,
            invoice_reference, invoice_date, due_date, period_start,
            period_end, amount_minor_units, currency, notes,
            created_by_user_id, updated_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            safe_engagement_id,
            billing_arrangement_id,
            clean_reference,
            safe_invoice_date,
            safe_due_date,
            safe_period_start,
            safe_period_end,
            safe_amount,
            clean_currency,
            clean_notes,
            actor_id,
            actor_id,
        ),
    )
    return get_invoice(db, cursor.lastrowid, organization_id=safe_organization_id)


def update_invoice_status(
    db: sqlite3.Connection,
    invoice_id: int,
    *,
    actor: Record,
    organization_id: int,
    status: str,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    _require_owner(db, actor, safe_organization_id)

    current = get_invoice(db, invoice_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Invoice not found.")
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This invoice changed in another session.")

    clean_status = str(status or "").strip().casefold()
    if clean_status not in INVOICE_STATUSES:
        raise ValueError("Unsupported invoice status.")

    cursor = db.execute(
        """
        UPDATE invoices
        SET status = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
          AND (? IS NULL OR row_version = ?)
        """,
        (
            clean_status,
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This invoice changed in another session.")
    return get_invoice(db, invoice_id, organization_id=safe_organization_id)


# ---------------------------------------------------------------------------
# Payments (append-only; corrections are voids, never edits/deletes)
# ---------------------------------------------------------------------------


def list_payments_for_invoice(
    db: sqlite3.Connection, invoice_id: int, *, organization_id: int
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT * FROM payments
        WHERE invoice_id = ? AND organization_id = ?
        ORDER BY payment_date DESC, id DESC
        """,
        (
            _positive_id(invoice_id, "Invoice ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def get_payment(
    db: sqlite3.Connection, payment_id: int, *, organization_id: int
) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT * FROM payments WHERE id = ? AND organization_id = ?",
        (
            _positive_id(payment_id, "Payment ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchone()
    return dict(row) if row is not None else None


def record_payment(
    db: sqlite3.Connection,
    invoice_id: int,
    *,
    actor: Record,
    organization_id: int,
    amount_minor_units: int,
    payment_date: str,
    currency: str = "PHP",
    payment_method: str = "",
    reference: str = "",
    notes: str = "",
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _require_owner(db, actor, safe_organization_id)
    safe_invoice_id = _positive_id(invoice_id, "Invoice ID")
    invoice = get_invoice(db, safe_invoice_id, organization_id=safe_organization_id)
    if invoice is None:
        raise ValueError("Invoice not found.")

    safe_amount = _required_amount(amount_minor_units, "Amount", allow_zero=False)
    clean_currency = _clean_currency(currency)
    safe_payment_date = _required_date_text(payment_date, "Payment date")
    clean_method = _optional_text(payment_method, "Payment method", MAX_TEXT_LENGTH)
    clean_reference = _optional_text(reference, "Reference", MAX_TEXT_LENGTH)
    clean_notes = _optional_text(notes, "Notes", MAX_LONG_TEXT_LENGTH)

    actor_id = _actor_id(actor)
    cursor = db.execute(
        """
        INSERT INTO payments (
            organization_id, invoice_id, amount_minor_units, currency,
            payment_date, payment_method, reference, notes, created_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            safe_invoice_id,
            safe_amount,
            clean_currency,
            safe_payment_date,
            clean_method,
            clean_reference,
            clean_notes,
            actor_id,
        ),
    )
    return get_payment(db, cursor.lastrowid, organization_id=safe_organization_id)


def void_payment(
    db: sqlite3.Connection,
    payment_id: int,
    *,
    actor: Record,
    organization_id: int,
    void_reason: str,
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _require_owner(db, actor, safe_organization_id)

    current = get_payment(db, payment_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Payment not found.")
    if current["voided_at"] is not None:
        raise ValueError("This payment is already voided.")

    clean_reason = _required_text(void_reason, "Void reason", MAX_LONG_TEXT_LENGTH)
    actor_id = _actor_id(actor)
    cursor = db.execute(
        """
        UPDATE payments
        SET voided_at = CURRENT_TIMESTAMP, voided_by_user_id = ?, void_reason = ?
        WHERE id = ? AND organization_id = ? AND voided_at IS NULL
        """,
        (actor_id, clean_reason, int(current["id"]), safe_organization_id),
    )
    if cursor.rowcount != 1:
        raise ValueError("This payment is already voided.")
    return get_payment(db, payment_id, organization_id=safe_organization_id)


# ---------------------------------------------------------------------------
# Engagement costs
# ---------------------------------------------------------------------------


def list_engagement_costs(
    db: sqlite3.Connection, engagement_id: int, *, organization_id: int
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT * FROM engagement_costs
        WHERE engagement_id = ? AND organization_id = ? AND deleted_at IS NULL
        ORDER BY incurred_date DESC, id DESC
        """,
        (
            _positive_id(engagement_id, "Engagement ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def get_engagement_cost(
    db: sqlite3.Connection, cost_id: int, *, organization_id: int
) -> dict[str, Any] | None:
    row = db.execute(
        """
        SELECT * FROM engagement_costs
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
        """,
        (
            _positive_id(cost_id, "Cost ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchone()
    return dict(row) if row is not None else None


def create_engagement_cost(
    db: sqlite3.Connection,
    engagement_id: int,
    *,
    actor: Record,
    organization_id: int,
    cost_type: str,
    description: str,
    amount_minor_units: int,
    incurred_date: str,
    currency: str = "PHP",
    paid_to: str = "",
    notes: str = "",
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _require_owner(db, actor, safe_organization_id)
    safe_engagement_id = _positive_id(engagement_id, "Engagement ID")
    _require_engagement(db, safe_engagement_id, safe_organization_id)

    clean_type = str(cost_type or "").strip().casefold()
    if clean_type not in ENGAGEMENT_COST_TYPES:
        raise ValueError("Unsupported cost type.")
    clean_description = _required_text(description, "Description", MAX_TEXT_LENGTH)
    safe_amount = _required_amount(amount_minor_units, "Amount")
    clean_currency = _clean_currency(currency)
    safe_incurred_date = _required_date_text(incurred_date, "Incurred date")
    clean_paid_to = _optional_text(paid_to, "Paid to", MAX_TEXT_LENGTH)
    clean_notes = _optional_text(notes, "Notes", MAX_LONG_TEXT_LENGTH)

    actor_id = _actor_id(actor)
    cursor = db.execute(
        """
        INSERT INTO engagement_costs (
            organization_id, engagement_id, cost_type, description,
            amount_minor_units, currency, incurred_date, paid_to, notes,
            created_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            safe_engagement_id,
            clean_type,
            clean_description,
            safe_amount,
            clean_currency,
            safe_incurred_date,
            clean_paid_to,
            clean_notes,
            actor_id,
        ),
    )
    return get_engagement_cost(db, cursor.lastrowid, organization_id=safe_organization_id)


def delete_engagement_cost(
    db: sqlite3.Connection,
    cost_id: int,
    *,
    actor: Record,
    organization_id: int,
) -> None:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    _require_owner(db, actor, safe_organization_id)

    current = get_engagement_cost(db, cost_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Cost record not found.")

    cursor = db.execute(
        """
        UPDATE engagement_costs
        SET deleted_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
        """,
        (int(current["id"]), safe_organization_id),
    )
    if cursor.rowcount != 1:
        raise ValueError("Cost record not found.")


# ---------------------------------------------------------------------------
# Profitability (fully computed, nothing cached)
# ---------------------------------------------------------------------------


def compute_engagement_profitability(
    db: sqlite3.Connection,
    engagement_id: int,
    *,
    actor: Record,
    organization_id: int,
) -> EngagementProfitability:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    _require_owner(db, actor, safe_organization_id)
    safe_engagement_id = _positive_id(engagement_id, "Engagement ID")
    _require_engagement(db, safe_engagement_id, safe_organization_id)

    collected_revenue = int(
        db.execute(
            """
            SELECT COALESCE(SUM(p.amount_minor_units), 0)
            FROM payments AS p
            JOIN invoices AS i ON i.id = p.invoice_id
            WHERE i.engagement_id = ?
              AND i.organization_id = ?
              AND i.deleted_at IS NULL
              AND p.voided_at IS NULL
            """,
            (safe_engagement_id, safe_organization_id),
        ).fetchone()[0]
    )

    total_costs = int(
        db.execute(
            """
            SELECT COALESCE(SUM(amount_minor_units), 0)
            FROM engagement_costs
            WHERE engagement_id = ? AND organization_id = ? AND deleted_at IS NULL
            """,
            (safe_engagement_id, safe_organization_id),
        ).fetchone()[0]
    )

    gross_profit = collected_revenue - total_costs
    margin = (gross_profit / collected_revenue) if collected_revenue > 0 else None

    arrangement = db.execute(
        """
        SELECT commission_rate_basis_points
        FROM billing_arrangements
        WHERE engagement_id = ? AND organization_id = ? AND status = 'active'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (safe_engagement_id, safe_organization_id),
    ).fetchone()

    commission_rate = (
        int(arrangement["commission_rate_basis_points"])
        if arrangement is not None and arrangement["commission_rate_basis_points"] is not None
        else None
    )
    commission = (
        (collected_revenue * commission_rate) // 10_000
        if commission_rate is not None
        else None
    )

    return EngagementProfitability(
        engagement_id=safe_engagement_id,
        collected_revenue_minor_units=collected_revenue,
        total_costs_minor_units=total_costs,
        gross_profit_minor_units=gross_profit,
        margin=margin,
        commission_minor_units=commission,
        commission_rate_basis_points=commission_rate,
    )
