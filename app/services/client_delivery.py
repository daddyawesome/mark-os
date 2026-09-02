from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from app.db.client_delivery import ENGAGEMENT_ITEM_TYPES
from app.services.client_delivery_permissions import (
    ClientDeliveryPermissionError,
    can_cancel_engagement,
    can_complete_engagement,
    can_manage_clients,
    can_manage_engagement_items,
    can_update_engagement_notes,
)
from app.services.leads import get_lead
from app.services.workspace_context import load_crm_actor_for_workspace


Record = Mapping[str, Any]

MAX_TEXT_LENGTH = 500
MAX_LONG_TEXT_LENGTH = 4_000
MAX_URL_LENGTH = 2_000


class ClientDeliveryStateError(ValueError):
    """Raised when a client-delivery action is invalid for its current state."""


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
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


def _required_text(value: Any, field_name: str, maximum: int) -> str:
    clean = _optional_text(value, field_name, maximum)
    if not clean:
        raise ValueError(f"{field_name} is required.")
    return clean


def _optional_date_text(value: Any, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    return value.strip()


def _optional_user_id(
    db: sqlite3.Connection, value: Any, organization_id: int, field_name: str
) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must reference a user.")
    row = db.execute(
        """
        SELECT users.id
        FROM users
        JOIN organization_memberships AS membership
          ON membership.user_id = users.id
         AND membership.organization_id = ?
        WHERE users.id = ? AND users.active = 1 AND membership.active = 1
        """,
        (organization_id, value),
    ).fetchone()
    if row is None:
        raise ValueError(f"{field_name} must reference an active workspace user.")
    return int(row["id"])


def _actor_for_workspace(db: sqlite3.Connection, actor: Record, organization_id: int) -> Record:
    try:
        return load_crm_actor_for_workspace(db, actor, organization_id)
    except PermissionError as exc:
        raise ClientDeliveryPermissionError(
            "You are not allowed to access this CRM workspace."
        ) from exc


def _actor_id(actor: Record) -> int | None:
    value = actor.get("id") if hasattr(actor, "get") else None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


def get_client(db: sqlite3.Connection, client_id: int, *, organization_id: int) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT * FROM organization_clients WHERE id = ? AND organization_id = ?",
        (_positive_id(client_id, "Client ID"), _positive_id(organization_id, "Organization ID")),
    ).fetchone()
    return dict(row) if row is not None else None


def get_client_by_lead(
    db: sqlite3.Connection, lead_id: int, *, organization_id: int
) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT * FROM organization_clients WHERE lead_id = ? AND organization_id = ?",
        (_positive_id(lead_id, "Lead ID"), _positive_id(organization_id, "Organization ID")),
    ).fetchone()
    return dict(row) if row is not None else None


def list_clients(db: sqlite3.Connection, *, organization_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM organization_clients WHERE organization_id = ? "
        "ORDER BY created_at DESC, id DESC",
        (_positive_id(organization_id, "Organization ID"),),
    ).fetchall()
    return [dict(row) for row in rows]


def onboard_client_from_lead(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    organization_id: int,
    engagement_title: str,
) -> dict[str, Any]:
    """Turn a Won lead into a client and its first engagement, idempotently.

    Calling this twice for the same lead returns the existing client rather
    than creating a duplicate — the ``lead_id`` UNIQUE constraint on
    ``organization_clients`` makes this safe at the database layer, not just
    in application logic.
    """
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    if not can_manage_clients(actor):
        raise ClientDeliveryPermissionError(
            "Only Mark or workspace-owner authority can onboard a client."
        )

    safe_lead_id = _positive_id(lead_id, "Lead ID")
    lead = get_lead(db, safe_lead_id, organization_id=safe_organization_id)
    if lead is None:
        raise ValueError("Lead not found.")

    existing = get_client_by_lead(db, safe_lead_id, organization_id=safe_organization_id)
    if existing is not None:
        return existing

    if str(lead["pipeline_status"] or "") != "won":
        raise ClientDeliveryStateError(
            "A lead must be Won before it can be onboarded as a client."
        )

    clean_title = _required_text(engagement_title, "Engagement title", MAX_TEXT_LENGTH)
    actor_id = _actor_id(actor)

    cursor = db.execute(
        """
        INSERT INTO organization_clients (
            organization_id, lead_id, company, contact_person, created_by_user_id
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            safe_lead_id,
            str(lead["company"]),
            str(lead["contact_person"]),
            actor_id,
        ),
    )
    client_id = cursor.lastrowid

    db.execute(
        """
        INSERT INTO client_engagements (
            organization_id, client_id, title, delivery_owner_user_id,
            created_by_user_id, updated_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            client_id,
            clean_title,
            lead["business_development_owner_user_id"],
            actor_id,
            actor_id,
        ),
    )

    return get_client(db, client_id, organization_id=safe_organization_id)


# ---------------------------------------------------------------------------
# Engagements
# ---------------------------------------------------------------------------


def get_engagement(
    db: sqlite3.Connection, engagement_id: int, *, organization_id: int
) -> dict[str, Any] | None:
    row = db.execute(
        """
        SELECT * FROM client_engagements
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
        """,
        (
            _positive_id(engagement_id, "Engagement ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchone()
    return dict(row) if row is not None else None


def list_engagements_for_client(
    db: sqlite3.Connection, client_id: int, *, organization_id: int
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT * FROM client_engagements
        WHERE client_id = ? AND organization_id = ? AND deleted_at IS NULL
        ORDER BY created_at DESC, id DESC
        """,
        (
            _positive_id(client_id, "Client ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def create_engagement(
    db: sqlite3.Connection,
    client_id: int,
    *,
    actor: Record,
    organization_id: int,
    title: str,
    delivery_owner_user_id: int | None = None,
    success_criteria: str = "",
    deliverables: str = "",
    contract_url: str = "",
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    if not can_manage_clients(actor):
        raise ClientDeliveryPermissionError(
            "Only Mark or workspace-owner authority can create engagements."
        )

    safe_client_id = _positive_id(client_id, "Client ID")
    if get_client(db, safe_client_id, organization_id=safe_organization_id) is None:
        raise ValueError("Client not found.")

    clean_title = _required_text(title, "Engagement title", MAX_TEXT_LENGTH)
    safe_delivery_owner = _optional_user_id(
        db, delivery_owner_user_id, safe_organization_id, "Delivery owner"
    )
    clean_success_criteria = _optional_text(
        success_criteria, "Success criteria", MAX_LONG_TEXT_LENGTH
    )
    clean_deliverables = _optional_text(deliverables, "Deliverables", MAX_LONG_TEXT_LENGTH)
    clean_contract_url = _optional_text(contract_url, "Contract URL", MAX_URL_LENGTH)
    actor_id = _actor_id(actor)

    cursor = db.execute(
        """
        INSERT INTO client_engagements (
            organization_id, client_id, title, delivery_owner_user_id,
            success_criteria, deliverables, contract_url,
            created_by_user_id, updated_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            safe_client_id,
            clean_title,
            safe_delivery_owner,
            clean_success_criteria,
            clean_deliverables,
            clean_contract_url,
            actor_id,
            actor_id,
        ),
    )
    return get_engagement(db, cursor.lastrowid, organization_id=safe_organization_id)


def update_engagement(
    db: sqlite3.Connection,
    engagement_id: int,
    *,
    actor: Record,
    organization_id: int,
    expected_row_version: int | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Owner-only structural edit: title, delivery owner, scope fields."""
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    if not can_manage_clients(actor):
        raise ClientDeliveryPermissionError(
            "Only Mark or workspace-owner authority can edit engagement scope."
        )

    current = get_engagement(db, engagement_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Engagement not found.")
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This engagement changed in another session.")
    if current["status"] != "active":
        raise ClientDeliveryStateError(
            "Only an active engagement's scope can be edited."
        )

    clean_title = _required_text(
        fields.get("title", current["title"]), "Engagement title", MAX_TEXT_LENGTH
    )
    safe_delivery_owner = _optional_user_id(
        db,
        fields.get("delivery_owner_user_id", current["delivery_owner_user_id"]),
        safe_organization_id,
        "Delivery owner",
    )
    clean_success_criteria = _optional_text(
        fields.get("success_criteria", current["success_criteria"]),
        "Success criteria",
        MAX_LONG_TEXT_LENGTH,
    )
    clean_deliverables = _optional_text(
        fields.get("deliverables", current["deliverables"]),
        "Deliverables",
        MAX_LONG_TEXT_LENGTH,
    )
    clean_contract_url = _optional_text(
        fields.get("contract_url", current["contract_url"]),
        "Contract URL",
        MAX_URL_LENGTH,
    )
    actor_id = _actor_id(actor)

    cursor = db.execute(
        """
        UPDATE client_engagements
        SET title = ?, delivery_owner_user_id = ?, success_criteria = ?,
            deliverables = ?, contract_url = ?, updated_by_user_id = ?,
            row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
          AND (? IS NULL OR row_version = ?)
        """,
        (
            clean_title,
            safe_delivery_owner,
            clean_success_criteria,
            clean_deliverables,
            clean_contract_url,
            actor_id,
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This engagement changed in another session.")
    return get_engagement(db, engagement_id, organization_id=safe_organization_id)


def update_engagement_notes(
    db: sqlite3.Connection,
    engagement_id: int,
    *,
    actor: Record,
    organization_id: int,
    notes: str,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    """The delivery owner keeps working notes current without scope authority."""
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    current = get_engagement(db, engagement_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Engagement not found.")
    if not can_update_engagement_notes(actor, current):
        raise ClientDeliveryPermissionError(
            "You are not allowed to update this engagement's notes."
        )
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This engagement changed in another session.")

    clean_notes = _optional_text(notes, "Notes", MAX_LONG_TEXT_LENGTH)
    cursor = db.execute(
        """
        UPDATE client_engagements
        SET notes = ?, updated_by_user_id = ?, row_version = row_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
          AND (? IS NULL OR row_version = ?)
        """,
        (
            clean_notes,
            _actor_id(actor),
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This engagement changed in another session.")
    return get_engagement(db, engagement_id, organization_id=safe_organization_id)


def _finalize_engagement_status(
    db: sqlite3.Connection,
    engagement_id: int,
    *,
    actor: Record,
    organization_id: int,
    expected_row_version: int | None,
    target_status: str,
    permission_check,
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    current = get_engagement(db, engagement_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Engagement not found.")
    if not permission_check(actor, current):
        raise ClientDeliveryPermissionError(
            "You are not allowed to change this engagement's status."
        )
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This engagement changed in another session.")

    completed_at_clause = (
        "completed_at = CURRENT_TIMESTAMP," if target_status == "completed" else ""
    )
    cursor = db.execute(
        f"""
        UPDATE client_engagements
        SET status = ?, {completed_at_clause}
            row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
          AND status = 'active'
          AND (? IS NULL OR row_version = ?)
        """,
        (
            target_status,
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This engagement changed in another session.")
    return get_engagement(db, engagement_id, organization_id=safe_organization_id)


def complete_engagement(
    db: sqlite3.Connection,
    engagement_id: int,
    *,
    actor: Record,
    organization_id: int,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    return _finalize_engagement_status(
        db,
        engagement_id,
        actor=actor,
        organization_id=organization_id,
        expected_row_version=expected_row_version,
        target_status="completed",
        permission_check=can_complete_engagement,
    )


def cancel_engagement(
    db: sqlite3.Connection,
    engagement_id: int,
    *,
    actor: Record,
    organization_id: int,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    return _finalize_engagement_status(
        db,
        engagement_id,
        actor=actor,
        organization_id=organization_id,
        expected_row_version=expected_row_version,
        target_status="cancelled",
        permission_check=can_cancel_engagement,
    )


# ---------------------------------------------------------------------------
# Engagement items (milestones and tasks)
# ---------------------------------------------------------------------------


def list_engagement_items(
    db: sqlite3.Connection, engagement_id: int, *, organization_id: int
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT * FROM engagement_items
        WHERE engagement_id = ? AND organization_id = ? AND deleted_at IS NULL
        ORDER BY
            CASE status WHEN 'in_progress' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
            COALESCE(due_date, '9999-12-31'),
            id
        """,
        (
            _positive_id(engagement_id, "Engagement ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def get_engagement_item(
    db: sqlite3.Connection, item_id: int, *, organization_id: int
) -> dict[str, Any] | None:
    row = db.execute(
        """
        SELECT * FROM engagement_items
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
        """,
        (
            _positive_id(item_id, "Item ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    ).fetchone()
    return dict(row) if row is not None else None


def create_engagement_item(
    db: sqlite3.Connection,
    engagement_id: int,
    *,
    actor: Record,
    organization_id: int,
    item_type: str,
    title: str,
    description: str = "",
    due_date: str | None = None,
    assigned_to_user_id: int | None = None,
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    engagement = get_engagement(db, engagement_id, organization_id=safe_organization_id)
    if engagement is None:
        raise ValueError("Engagement not found.")
    if not can_manage_engagement_items(actor, engagement):
        raise ClientDeliveryPermissionError(
            "You are not allowed to add items to this engagement."
        )

    clean_item_type = str(item_type or "").strip().casefold()
    if clean_item_type not in ENGAGEMENT_ITEM_TYPES:
        raise ValueError("Item type must be 'milestone' or 'task'.")
    clean_title = _required_text(title, "Title", MAX_TEXT_LENGTH)
    clean_description = _optional_text(description, "Description", MAX_LONG_TEXT_LENGTH)
    safe_due_date = _optional_date_text(due_date, "Due date")
    safe_assignee = _optional_user_id(
        db, assigned_to_user_id, safe_organization_id, "Assignee"
    )
    actor_id = _actor_id(actor)

    cursor = db.execute(
        """
        INSERT INTO engagement_items (
            organization_id, engagement_id, item_type, title, description,
            due_date, assigned_to_user_id, created_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            int(engagement["id"]),
            clean_item_type,
            clean_title,
            clean_description,
            safe_due_date,
            safe_assignee,
            actor_id,
        ),
    )
    return get_engagement_item(db, cursor.lastrowid, organization_id=safe_organization_id)


def update_engagement_item_status(
    db: sqlite3.Connection,
    item_id: int,
    *,
    actor: Record,
    organization_id: int,
    status: str,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    current = get_engagement_item(db, item_id, organization_id=safe_organization_id)
    if current is None:
        raise ValueError("Engagement item not found.")
    engagement = get_engagement(
        db, current["engagement_id"], organization_id=safe_organization_id
    )
    if not can_manage_engagement_items(actor, engagement):
        raise ClientDeliveryPermissionError(
            "You are not allowed to update this item."
        )
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This item changed in another session.")

    clean_status = str(status or "").strip().casefold()
    from app.db.client_delivery import ENGAGEMENT_ITEM_STATUSES

    if clean_status not in ENGAGEMENT_ITEM_STATUSES:
        raise ValueError("Unsupported item status.")

    actor_id = _actor_id(actor)
    is_completing = clean_status == "completed"
    cursor = db.execute(
        """
        UPDATE engagement_items
        SET status = ?,
            completed_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
            completed_by_user_id = CASE WHEN ? THEN ? ELSE NULL END,
            row_version = row_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND deleted_at IS NULL
          AND (? IS NULL OR row_version = ?)
        """,
        (
            clean_status,
            is_completing,
            is_completing,
            actor_id,
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This item changed in another session.")
    return get_engagement_item(db, item_id, organization_id=safe_organization_id)
