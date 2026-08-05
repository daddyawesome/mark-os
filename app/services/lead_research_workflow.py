from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from app.services.lead_research_permissions import (
    SOURCER_RESEARCH_EDIT_FIELDS,
    LeadPermissionError,
    require_edit_fields,
)
from app.services.leads import get_lead, update_lead


Record = Mapping[str, Any]

RESEARCH_EDIT_FIELDS = tuple(
    sorted(SOURCER_RESEARCH_EDIT_FIELDS)
)


def _actor_id(actor: Record | None) -> int:
    if actor is None:
        raise LeadPermissionError(
            "An authenticated user is required."
        )

    value = actor.get("id")
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise LeadPermissionError(
            "The authenticated user is invalid."
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


def update_research_details(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    company: str,
    contact_person: str,
    source: str,
    problem_opportunity: str,
    why_mark_fits: str,
    next_action: str,
    job_title: str = "",
    source_url: str = "",
    next_action_due_date: str | None = None,
    notes: str = "",
) -> sqlite3.Row:
    """Save only research fields for an authorized CRM actor."""
    actor_id = _actor_id(actor)
    current = _require_active_lead(db, lead_id)

    require_edit_fields(
        actor,
        current,
        RESEARCH_EDIT_FIELDS,
    )

    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")

    db.execute(
        "SAVEPOINT lead_research_edit"
    )

    try:
        updated = update_lead(
            db,
            lead_id,
            company=company,
            contact_person=contact_person,
            job_title=job_title,
            source=source,
            source_url=source_url,
            problem_opportunity=problem_opportunity,
            why_mark_fits=why_mark_fits,
            next_action=next_action,
            next_action_due_date=(
                next_action_due_date
                if next_action_due_date
                else None
            ),
            notes=notes,
        )

        previous_status = str(
            current["research_status"]
            or ""
        ).strip().casefold()

        next_status = (
            "researching"
            if previous_status
            in {"draft", "changes_requested"}
            else previous_status
        )

        cursor = db.execute(
            """
            UPDATE leads
            SET
                researched_by_user_id = COALESCE(
                    researched_by_user_id,
                    ?
                ),
                research_status = ?,
                submitted_for_review_at = CASE
                    WHEN ? = 'changes_requested'
                    THEN NULL
                    ELSE submitted_for_review_at
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND deleted_at IS NULL
            """,
            (
                actor_id,
                next_status,
                previous_status,
                lead_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Lead not found")

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
                'crm_research_saved'
            FROM tasks
            WHERE id = ?
            """,
            (
                (
                    "Lead research saved by user "
                    f"#{actor_id}."
                ),
                updated["quest_id"],
            ),
        )

    except BaseException:
        db.execute(
            "ROLLBACK TO SAVEPOINT "
            "lead_research_edit"
        )
        db.execute(
            "RELEASE SAVEPOINT "
            "lead_research_edit"
        )
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute(
            "RELEASE SAVEPOINT "
            "lead_research_edit"
        )

    result = get_lead(db, lead_id)
    if result is None:
        raise RuntimeError(
            "Updated lead could not be reloaded"
        )
    return result


def submit_research_for_review(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
) -> sqlite3.Row:
    """Place eligible lead research in the Owner review queue."""
    from app.services.lead_research_permissions import (
        can_submit_for_review,
    )

    actor_id = _actor_id(actor)
    current = _require_active_lead(db, lead_id)

    if not can_submit_for_review(actor, current):
        raise LeadPermissionError(
            "You are not allowed to submit this lead "
            "for research review."
        )

    previous_status = str(
        current["research_status"] or ""
    ).strip().casefold()

    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")

    db.execute(
        "SAVEPOINT lead_research_submit"
    )

    try:
        cursor = db.execute(
            """
            UPDATE leads
            SET
                researched_by_user_id = COALESCE(
                    researched_by_user_id,
                    ?
                ),
                research_status = 'ready_for_review',
                submitted_for_review_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND deleted_at IS NULL
              AND research_status = ?
            """,
            (
                actor_id,
                lead_id,
                previous_status,
            ),
        )
        if cursor.rowcount != 1:
            raise LeadPermissionError(
                "The lead changed before submission. "
                "Reload and try again."
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
                'crm_research_submitted'
            FROM tasks
            WHERE id = ?
            """,
            (
                (
                    "Lead research submitted for Owner "
                    f"review by user #{actor_id}."
                ),
                current["quest_id"],
            ),
        )

    except BaseException:
        db.execute(
            "ROLLBACK TO SAVEPOINT "
            "lead_research_submit"
        )
        db.execute(
            "RELEASE SAVEPOINT "
            "lead_research_submit"
        )
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute(
            "RELEASE SAVEPOINT "
            "lead_research_submit"
        )

    result = get_lead(db, lead_id)
    if result is None:
        raise RuntimeError(
            "Submitted lead could not be reloaded"
        )
    return result


def list_research_review_queue(
    db: sqlite3.Connection,
) -> list[sqlite3.Row]:
    """Return active leads waiting for an Owner research decision."""
    return db.execute(
        """
        SELECT
            l.*,
            creator.display_name AS created_by_name,
            creator.username AS created_by_username,
            assignee.display_name AS assigned_to_name,
            assignee.username AS assigned_to_username,
            researcher.display_name AS researched_by_name,
            researcher.username AS researched_by_username
        FROM leads AS l
        LEFT JOIN users AS creator
            ON creator.id = l.created_by_user_id
        LEFT JOIN users AS assignee
            ON assignee.id = l.assigned_to_user_id
        LEFT JOIN users AS researcher
            ON researcher.id = l.researched_by_user_id
        WHERE l.deleted_at IS NULL
          AND l.research_status = 'ready_for_review'
        ORDER BY
            COALESCE(
                l.submitted_for_review_at,
                l.updated_at
            ) ASC,
            CASE l.priority
                WHEN 'high' THEN 0
                WHEN 'medium' THEN 1
                ELSE 2
            END,
            l.id ASC
        """
    ).fetchall()
