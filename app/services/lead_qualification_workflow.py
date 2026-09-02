from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from app.services.lead_qualification_permissions import (
    LeadQualificationPermissionError,
    can_decide_qualification,
    can_edit_qualification,
    require_qualification_decision,
)
from app.services.leads import get_lead, require_lead_version
from app.services.workspace_context import load_crm_actor_for_workspace


Record = Mapping[str, Any]

QUALIFICATION_TEXT_FIELDS = (
    "business_problem",
    "business_impact",
    "current_process",
    "current_tools",
    "estimated_hours_wasted",
    "urgency",
    "budget_range",
    "decision_maker",
    "desired_result",
    "meeting_notes",
    "recommended_service",
)

MAX_QUALIFICATION_FIELD_LENGTH = 4_000


def _actor_id(actor: Record | None) -> int:
    if actor is None:
        raise LeadQualificationPermissionError(
            "An authenticated user is required."
        )
    value = actor.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LeadQualificationPermissionError(
            "The authenticated user is invalid."
        )
    return value


def _actor_for_workspace(
    db: sqlite3.Connection,
    actor: Record,
    organization_id: int | None,
) -> Record:
    if organization_id is None:
        return actor
    try:
        return load_crm_actor_for_workspace(db, actor, organization_id)
    except PermissionError as exc:
        raise LeadQualificationPermissionError(
            "You are not allowed to access this CRM workspace."
        ) from exc


def _require_active_lead(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    organization_id: int | None = None,
) -> sqlite3.Row:
    lead = get_lead(db, lead_id, organization_id=organization_id)
    if lead is None:
        raise ValueError("Lead not found")
    return lead


def _clean_field(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = " ".join(value.strip().split())
    if len(clean) > MAX_QUALIFICATION_FIELD_LENGTH:
        raise ValueError(
            f"{field_name} must be {MAX_QUALIFICATION_FIELD_LENGTH} "
            "characters or fewer."
        )
    return clean


def update_qualification_details(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    organization_id: int | None = None,
    expected_row_version: int | None = None,
    **fields: Any,
) -> sqlite3.Row:
    """Save discovery/qualification notes for one lead.

    Purely a data update: it never changes pipeline_status, never creates a
    proposal, and never decides the lead's fit. Only ``decide_qualification``
    (Owner/workspace-owner authority only) can set a final qualified or
    disqualified state.
    """
    actor = _actor_for_workspace(db, actor, organization_id)
    actor_id = _actor_id(actor)
    current = _require_active_lead(db, lead_id, organization_id=organization_id)
    safe_organization_id = int(current["organization_id"])
    require_lead_version(current, expected_row_version)

    if not can_edit_qualification(actor, current):
        raise LeadQualificationPermissionError(
            "You are not allowed to edit this lead's qualification."
        )

    unknown_fields = set(fields) - set(QUALIFICATION_TEXT_FIELDS)
    if unknown_fields:
        raise ValueError(
            "Unsupported qualification field(s): "
            + ", ".join(sorted(unknown_fields))
        )

    clean_values = {
        name: _clean_field(fields.get(name, ""), name)
        for name in QUALIFICATION_TEXT_FIELDS
    }

    current_status = str(current["qualification_status"] or "")
    next_status = (
        "in_progress" if current_status == "not_started" else current_status
    )

    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT lead_qualification_edit")

    try:
        set_clause = ", ".join(f"{name} = ?" for name in QUALIFICATION_TEXT_FIELDS)
        cursor = db.execute(
            f"""
            UPDATE leads
            SET {set_clause},
                qualification_status = ?,
                qualification_updated_by_user_id = ?,
                qualification_updated_at = CURRENT_TIMESTAMP,
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
              AND row_version = ?
            """,
            (
                *(clean_values[name] for name in QUALIFICATION_TEXT_FIELDS),
                next_status,
                actor_id,
                lead_id,
                safe_organization_id,
                int(current["row_version"]),
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("This lead changed in another session.")

        db.execute(
            """
            INSERT INTO quest_updates (
                user_id, task_id, note, progress, event_type
            )
            SELECT user_id, id, ?, progress, 'crm_qualification_updated'
            FROM tasks
            WHERE id = ?
            """,
            (
                f"Qualification notes updated by user #{actor_id}.",
                current["quest_id"],
            ),
        )
    except BaseException:
        db.execute("ROLLBACK TO SAVEPOINT lead_qualification_edit")
        db.execute("RELEASE SAVEPOINT lead_qualification_edit")
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute("RELEASE SAVEPOINT lead_qualification_edit")

    result = get_lead(db, lead_id, organization_id=safe_organization_id)
    if result is None:
        raise RuntimeError("Updated lead could not be reloaded")
    return result


def decide_qualification(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    decision: str,
    organization_id: int | None = None,
    expected_row_version: int | None = None,
) -> sqlite3.Row:
    """Apply Mark's final qualified/disqualified decision to one lead.

    Never touches pipeline_status and never creates a proposal — a high
    qualification outcome is a fact recorded on the lead, not a trigger.
    """
    actor = _actor_for_workspace(db, actor, organization_id)
    actor_id = _actor_id(actor)
    current = _require_active_lead(db, lead_id, organization_id=organization_id)
    safe_organization_id = int(current["organization_id"])
    require_lead_version(current, expected_row_version)

    normalized_decision = require_qualification_decision(decision)

    if not can_decide_qualification(actor, current):
        raise LeadQualificationPermissionError(
            "You are not allowed to decide this lead's qualification."
        )

    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT lead_qualification_decide")

    try:
        cursor = db.execute(
            """
            UPDATE leads
            SET qualification_status = ?,
                qualification_decided_by_user_id = ?,
                qualification_decided_at = CURRENT_TIMESTAMP,
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
              AND row_version = ?
            """,
            (
                normalized_decision,
                actor_id,
                lead_id,
                safe_organization_id,
                int(current["row_version"]),
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("This lead changed in another session.")

        db.execute(
            """
            INSERT INTO quest_updates (
                user_id, task_id, note, progress, event_type
            )
            SELECT
                user_id, id,
                ?,
                progress,
                'crm_qualification_decided'
            FROM tasks
            WHERE id = ?
            """,
            (
                (
                    f"Qualification decided as {normalized_decision} "
                    f"by user #{actor_id}."
                ),
                current["quest_id"],
            ),
        )
    except BaseException:
        db.execute("ROLLBACK TO SAVEPOINT lead_qualification_decide")
        db.execute("RELEASE SAVEPOINT lead_qualification_decide")
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute("RELEASE SAVEPOINT lead_qualification_decide")

    result = get_lead(db, lead_id, organization_id=safe_organization_id)
    if result is None:
        raise RuntimeError("Decided lead could not be reloaded")
    return result
