from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any, Iterator

from app.services.lead_research_permissions import (
    LeadPermissionError,
    can_approve_outreach,
    require_pipeline_change,
)
from app.services.leads import (
    get_lead,
    update_lead,
    update_lead_pipeline,
)


Record = Mapping[str, Any]


class LeadPipelineRuleError(ValueError):
    """Raised when a permitted actor attempts an invalid CRM stage move."""


def _record_value(
    record: Record | sqlite3.Row | None,
    key: str,
    default: Any = None,
) -> Any:
    if record is None:
        return default
    try:
        return record[key]
    except (KeyError, IndexError, TypeError):
        return default


def _actor_id(actor: Record | None) -> int:
    value = _record_value(actor, "id")
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise LeadPermissionError(
            "An authenticated CRM actor is required."
        )
    return value


def _require_active_lead(
    db: sqlite3.Connection,
    lead_id: int,
) -> sqlite3.Row:
    lead = get_lead(db, lead_id)
    if lead is None:
        raise ValueError("Lead not found")
    return lead


@contextmanager
def _workflow_write(
    db: sqlite3.Connection,
    savepoint: str,
) -> Iterator[None]:
    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")
    else:
        db.execute("UPDATE leads SET id = id WHERE 0")

    db.execute(f"SAVEPOINT {savepoint}")
    try:
        yield
    except BaseException:
        db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        db.execute(f"RELEASE SAVEPOINT {savepoint}")
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute(f"RELEASE SAVEPOINT {savepoint}")


def _validate_major_transition(
    lead: sqlite3.Row,
    target_status: str,
) -> None:
    current_status = str(
        lead["pipeline_status"] or ""
    ).strip().casefold()

    if current_status == target_status:
        return

    if target_status == "contacted":
        if (
            str(lead["research_status"] or "")
            .strip()
            .casefold()
            != "approved"
        ):
            raise LeadPipelineRuleError(
                "Research must be approved before the "
                "lead can move to Contacted."
            )
        if (
            lead["outreach_approved_by_user_id"] is None
            or lead["outreach_approved_at"] is None
        ):
            raise LeadPipelineRuleError(
                "Owner outreach approval is required "
                "before the lead can move to Contacted."
            )

    if (
        target_status == "proposal"
        and current_status != "meeting"
    ):
        raise LeadPipelineRuleError(
            "A lead must be in Meeting before it can "
            "move to Proposal."
        )

    if (
        target_status == "won"
        and current_status != "proposal"
    ):
        raise LeadPipelineRuleError(
            "A lead must be in Proposal before it can "
            "move to Won."
        )

    # The roadmap permits any active pipeline state
    # to move to Lost in the first version.


def approve_outreach(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
) -> sqlite3.Row:
    """Record Owner approval before first outreach."""
    actor_id = _actor_id(actor)

    with _workflow_write(
        db,
        "lead_outreach_approval",
    ):
        current = _require_active_lead(db, lead_id)

        if not can_approve_outreach(actor, current):
            raise LeadPermissionError(
                "Only the Owner can approve outreach "
                "for approved research."
            )

        if (
            current["outreach_approved_by_user_id"]
            is not None
            and current["outreach_approved_at"]
            is not None
        ):
            return current

        cursor = db.execute(
            """
            UPDATE leads
            SET
                outreach_approved_by_user_id = ?,
                outreach_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND deleted_at IS NULL
              AND research_status = 'approved'
              AND outreach_approved_by_user_id IS NULL
              AND outreach_approved_at IS NULL
            """,
            (actor_id, lead_id),
        )

        if cursor.rowcount != 1:
            reloaded = _require_active_lead(
                db,
                lead_id,
            )
            if (
                reloaded[
                    "outreach_approved_by_user_id"
                ]
                is not None
                and reloaded["outreach_approved_at"]
                is not None
            ):
                return reloaded
            raise LeadPermissionError(
                "The lead changed before outreach "
                "approval could be saved."
            )

        db.execute(
            """
            INSERT INTO quest_updates (
                user_id,
                task_id,
                note,
                progress,
                event_type
            )
            SELECT
                user_id,
                id,
                ?,
                progress,
                'crm_outreach_approved'
            FROM tasks
            WHERE id = ?
            """,
            (
                (
                    "Outreach approved by Owner user "
                    f"#{actor_id}."
                ),
                current["quest_id"],
            ),
        )

    approved = get_lead(db, lead_id)
    if approved is None:
        raise RuntimeError(
            "Outreach-approved lead could not be "
            "reloaded."
        )
    return approved


def change_pipeline_stage(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    pipeline_status: str,
) -> sqlite3.Row:
    """Apply an Owner-authorized pipeline transition."""
    _actor_id(actor)

    with _workflow_write(
        db,
        "lead_pipeline_transition",
    ):
        current = _require_active_lead(db, lead_id)
        target_status = require_pipeline_change(
            actor,
            current,
            pipeline_status,
        )
        _validate_major_transition(
            current,
            target_status,
        )
        return update_lead_pipeline(
            db,
            lead_id,
            pipeline_status=target_status,
        )


def update_owner_lead(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    company: str,
    contact_person: str,
    source: str,
    problem_opportunity: str,
    why_mark_fits: str,
    pipeline_status: str,
    priority: str,
    next_action: str,
    job_title: str = "",
    source_url: str = "",
    next_action_due_date: str | None = None,
    notes: str = "",
) -> sqlite3.Row:
    """Protect pipeline changes made through the full Owner edit form."""
    _actor_id(actor)

    with _workflow_write(
        db,
        "lead_owner_full_edit",
    ):
        current = _require_active_lead(db, lead_id)
        target_status = require_pipeline_change(
            actor,
            current,
            pipeline_status,
        )
        _validate_major_transition(
            current,
            target_status,
        )

        return update_lead(
            db,
            lead_id,
            company=company,
            contact_person=contact_person,
            job_title=job_title,
            source=source,
            source_url=source_url,
            problem_opportunity=problem_opportunity,
            why_mark_fits=why_mark_fits,
            pipeline_status=target_status,
            priority=priority,
            next_action=next_action,
            next_action_due_date=next_action_due_date,
            notes=notes,
        )
