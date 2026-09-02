from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from app.db.proposals import DECISION_STATUSES, PROPOSAL_STATUSES
from app.services.leads import get_lead
from app.services.proposal_permissions import (
    ProposalPermissionError,
    can_manage_proposals,
)
from app.services.workspace_context import load_crm_actor_for_workspace


Record = Mapping[str, Any]

MAX_TEXT_LENGTH = 500
MAX_URL_LENGTH = 2_000

# draft -> internal_review -> approved -> sent, strictly forward, one step
# at a time. Nothing here ever touches the lead's own pipeline_status.
_NEXT_STATUS = {
    "draft": "internal_review",
    "internal_review": "approved",
    "approved": "sent",
}
_EDITABLE_STATUSES = frozenset({"draft", "internal_review"})


class ProposalStateError(ValueError):
    """Raised when a proposal action is invalid for its current state."""


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be a whole number.")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return value


def _optional_text(value: Any, field_name: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = " ".join(value.strip().split())
    if len(clean) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer.")
    return clean


def _optional_date_text(value: Any, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    return value.strip()


def _actor_for_workspace(db: sqlite3.Connection, actor: Record, organization_id: int) -> Record:
    try:
        return load_crm_actor_for_workspace(db, actor, organization_id)
    except PermissionError as exc:
        raise ProposalPermissionError(
            "You are not allowed to access this CRM workspace."
        ) from exc


def _actor_id(actor: Record) -> int | None:
    value = actor.get("id") if hasattr(actor, "get") else None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _require_lead(db: sqlite3.Connection, lead_id: int, organization_id: int) -> sqlite3.Row:
    lead = get_lead(db, lead_id, organization_id=organization_id)
    if lead is None:
        raise ValueError("Lead not found.")
    return lead


def get_proposal(
    db: sqlite3.Connection,
    proposal_id: int,
    *,
    organization_id: int,
) -> dict[str, Any] | None:
    row = db.execute(
        """
        SELECT *
        FROM proposals
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
        """,
        (
            _positive_id(proposal_id, "Proposal ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchone()
    return dict(row) if row is not None else None


def list_proposals_for_lead(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    organization_id: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT *
        FROM proposals
        WHERE lead_id = ? AND organization_id = ? AND deleted_at IS NULL
        ORDER BY created_at DESC, id DESC
        """,
        (
            _positive_id(lead_id, "Lead ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def create_proposal(
    db: sqlite3.Connection,
    *,
    actor: Record,
    organization_id: int,
    lead_id: int,
    service_offered: str,
    engagement_type: str = "",
    proposed_price_amount_minor_units: int | None = None,
    expected_monthly_value_amount_minor_units: int | None = None,
    currency: str = "PHP",
    proposal_url: str = "",
    proposal_expires_at: str | None = None,
    probability: int | None = None,
    follow_up_date: str | None = None,
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    if not can_manage_proposals(actor):
        raise ProposalPermissionError(
            "Only Mark or workspace-owner authority can create proposals."
        )

    safe_lead_id = _positive_id(lead_id, "Lead ID")
    _require_lead(db, safe_lead_id, safe_organization_id)

    clean_service = _optional_text(service_offered, "Service offered", MAX_TEXT_LENGTH)
    if not clean_service:
        raise ValueError("Service offered is required.")
    clean_engagement_type = _optional_text(
        engagement_type, "Engagement type", MAX_TEXT_LENGTH
    )
    clean_currency = _optional_text(currency, "Currency", 8) or "PHP"
    clean_url = _optional_text(proposal_url, "Proposal URL", MAX_URL_LENGTH)
    safe_price = _optional_positive_int(
        proposed_price_amount_minor_units, "Proposed price"
    )
    safe_monthly_value = _optional_positive_int(
        expected_monthly_value_amount_minor_units, "Expected monthly value"
    )
    safe_probability = _optional_positive_int(probability, "Probability")
    if safe_probability is not None and safe_probability > 100:
        raise ValueError("Probability must be between 0 and 100.")
    safe_expires_at = _optional_date_text(proposal_expires_at, "Proposal expiry date")
    safe_follow_up_date = _optional_date_text(follow_up_date, "Follow-up date")

    actor_id = _actor_id(actor)
    cursor = db.execute(
        """
        INSERT INTO proposals (
            organization_id, lead_id, service_offered, engagement_type,
            proposed_price_amount_minor_units,
            expected_monthly_value_amount_minor_units, currency,
            proposal_url, proposal_expires_at, probability, follow_up_date,
            created_by_user_id, updated_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            safe_lead_id,
            clean_service,
            clean_engagement_type,
            safe_price,
            safe_monthly_value,
            clean_currency,
            clean_url,
            safe_expires_at,
            safe_probability,
            safe_follow_up_date,
            actor_id,
            actor_id,
        ),
    )
    return get_proposal(db, cursor.lastrowid, organization_id=safe_organization_id)


def update_proposal(
    db: sqlite3.Connection,
    proposal_id: int,
    *,
    actor: Record,
    organization_id: int,
    expected_row_version: int | None = None,
    **fields: Any,
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    if not can_manage_proposals(actor):
        raise ProposalPermissionError(
            "Only Mark or workspace-owner authority can edit proposals."
        )

    current = get_proposal(db, proposal_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Proposal not found.")
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This proposal changed in another session.")
    if current["status"] not in _EDITABLE_STATUSES:
        raise ProposalStateError(
            "A proposal can only be edited while it is Draft or in "
            "Internal Review."
        )

    clean_service = _optional_text(
        fields.get("service_offered", current["service_offered"]),
        "Service offered",
        MAX_TEXT_LENGTH,
    )
    if not clean_service:
        raise ValueError("Service offered is required.")
    clean_engagement_type = _optional_text(
        fields.get("engagement_type", current["engagement_type"]),
        "Engagement type",
        MAX_TEXT_LENGTH,
    )
    clean_currency = (
        _optional_text(fields.get("currency", current["currency"]), "Currency", 8)
        or "PHP"
    )
    clean_url = _optional_text(
        fields.get("proposal_url", current["proposal_url"]),
        "Proposal URL",
        MAX_URL_LENGTH,
    )
    safe_price = _optional_positive_int(
        fields.get(
            "proposed_price_amount_minor_units",
            current["proposed_price_amount_minor_units"],
        ),
        "Proposed price",
    )
    safe_monthly_value = _optional_positive_int(
        fields.get(
            "expected_monthly_value_amount_minor_units",
            current["expected_monthly_value_amount_minor_units"],
        ),
        "Expected monthly value",
    )
    safe_probability = _optional_positive_int(
        fields.get("probability", current["probability"]), "Probability"
    )
    if safe_probability is not None and safe_probability > 100:
        raise ValueError("Probability must be between 0 and 100.")
    safe_expires_at = _optional_date_text(
        fields.get("proposal_expires_at", current["proposal_expires_at"]),
        "Proposal expiry date",
    )
    safe_follow_up_date = _optional_date_text(
        fields.get("follow_up_date", current["follow_up_date"]), "Follow-up date"
    )

    actor_id = _actor_id(actor)
    cursor = db.execute(
        """
        UPDATE proposals
        SET service_offered = ?,
            engagement_type = ?,
            proposed_price_amount_minor_units = ?,
            expected_monthly_value_amount_minor_units = ?,
            currency = ?,
            proposal_url = ?,
            proposal_expires_at = ?,
            probability = ?,
            follow_up_date = ?,
            updated_by_user_id = ?,
            row_version = row_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
          AND (? IS NULL OR row_version = ?)
        """,
        (
            clean_service,
            clean_engagement_type,
            safe_price,
            safe_monthly_value,
            clean_currency,
            clean_url,
            safe_expires_at,
            safe_probability,
            safe_follow_up_date,
            actor_id,
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This proposal changed in another session.")
    return get_proposal(db, proposal_id, organization_id=safe_organization_id)


def _advance_status(
    db: sqlite3.Connection,
    proposal_id: int,
    *,
    actor: Record,
    organization_id: int,
    expected_row_version: int | None,
    require_current_status: str,
    extra_set_clause: str = "",
    extra_params: tuple[Any, ...] = (),
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    if not can_manage_proposals(actor):
        raise ProposalPermissionError(
            "Only Mark or workspace-owner authority can manage this proposal."
        )

    current = get_proposal(db, proposal_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Proposal not found.")
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This proposal changed in another session.")
    if current["status"] != require_current_status:
        raise ProposalStateError(
            f"This proposal must be '{require_current_status}' for this "
            "action."
        )

    next_status = _NEXT_STATUS[require_current_status]
    actor_id = _actor_id(actor)
    set_clause = "status = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP"
    if extra_set_clause:
        set_clause += ", " + extra_set_clause

    cursor = db.execute(
        f"""
        UPDATE proposals
        SET {set_clause}
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
          AND status = ?
          AND (? IS NULL OR row_version = ?)
        """,
        (
            next_status,
            *extra_params,
            int(current["id"]),
            safe_organization_id,
            require_current_status,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This proposal changed in another session.")
    return get_proposal(db, proposal_id, organization_id=safe_organization_id)


def submit_proposal_for_internal_review(
    db: sqlite3.Connection,
    proposal_id: int,
    *,
    actor: Record,
    organization_id: int,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    return _advance_status(
        db,
        proposal_id,
        actor=actor,
        organization_id=organization_id,
        expected_row_version=expected_row_version,
        require_current_status="draft",
    )


def approve_proposal(
    db: sqlite3.Connection,
    proposal_id: int,
    *,
    actor: Record,
    organization_id: int,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor_for_id = _actor_for_workspace(db, actor, safe_organization_id)
    actor_id = _actor_id(actor_for_id)
    return _advance_status(
        db,
        proposal_id,
        actor=actor,
        organization_id=organization_id,
        expected_row_version=expected_row_version,
        require_current_status="internal_review",
        extra_set_clause="approved_by_user_id = ?, approved_at = CURRENT_TIMESTAMP",
        extra_params=(actor_id,),
    )


def send_proposal(
    db: sqlite3.Connection,
    proposal_id: int,
    *,
    actor: Record,
    organization_id: int,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    """Mark an approved proposal as sent/presented to the client.

    Requires a price and a link to already be set — MARK-OS does not
    generate or send the proposal document itself, so both must exist
    before this can be recorded as sent.
    """
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    current = get_proposal(db, proposal_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Proposal not found.")
    if current["proposed_price_amount_minor_units"] is None:
        raise ProposalStateError(
            "A proposed price is required before a proposal can be sent."
        )
    if not str(current["proposal_url"] or "").strip():
        raise ProposalStateError(
            "A proposal link is required before a proposal can be sent."
        )

    actor_for_id = _actor_for_workspace(db, actor, safe_organization_id)
    actor_id = _actor_id(actor_for_id)
    return _advance_status(
        db,
        proposal_id,
        actor=actor,
        organization_id=organization_id,
        expected_row_version=expected_row_version,
        require_current_status="approved",
        extra_set_clause=(
            "sent_by_user_id = ?, proposal_sent_at = CURRENT_TIMESTAMP"
        ),
        extra_params=(actor_id,),
    )


def record_proposal_decision(
    db: sqlite3.Connection,
    proposal_id: int,
    *,
    actor: Record,
    decision: str,
    decision_reason: str = "",
    organization_id: int,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    if not can_manage_proposals(actor):
        raise ProposalPermissionError(
            "Only Mark or workspace-owner authority can record a proposal "
            "decision."
        )

    normalized_decision = str(decision or "").strip().casefold()
    if normalized_decision not in DECISION_STATUSES:
        raise ValueError(
            "Decision must be one of: " + ", ".join(DECISION_STATUSES)
        )
    clean_reason = _optional_text(decision_reason, "Decision reason", 2_000)

    current = get_proposal(db, proposal_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Proposal not found.")
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This proposal changed in another session.")
    if current["status"] != "sent":
        raise ProposalStateError(
            "A decision can only be recorded once a proposal has been sent."
        )
    if current["decision_status"] is not None:
        raise ProposalStateError("This proposal already has a recorded decision.")

    cursor = db.execute(
        """
        UPDATE proposals
        SET decision_status = ?,
            decision_reason = ?,
            row_version = row_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
          AND status = 'sent' AND decision_status IS NULL
          AND (? IS NULL OR row_version = ?)
        """,
        (
            normalized_decision,
            clean_reason,
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This proposal changed in another session.")
    return get_proposal(db, proposal_id, organization_id=safe_organization_id)
