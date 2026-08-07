from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from app.db.organizations import organization_id_by_slug
from app.services.lead_research_permissions import (
    SOURCER_RESEARCH_EDIT_FIELDS,
    LeadPermissionError,
    require_edit_fields,
)
from app.services.leads import get_lead, require_lead_version, update_lead
from app.services.workspace_context import load_crm_actor_for_workspace


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


def _actor_for_workspace(
    db: sqlite3.Connection,
    actor: Record,
    organization_id: int | None,
) -> Record:
    if organization_id is None:
        return actor
    try:
        return load_crm_actor_for_workspace(
            db,
            actor,
            organization_id,
        )
    except PermissionError as exc:
        raise LeadPermissionError(
            "You are not allowed to access this CRM workspace."
        ) from exc


def _require_active_lead(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    organization_id: int | None = None,
) -> sqlite3.Row:
    lead = get_lead(
        db,
        lead_id,
        organization_id=organization_id,
    )
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
    organization_id: int | None = None,
    expected_row_version: int | None = None,
) -> sqlite3.Row:
    """Save research fields for an authorized actor in one workspace."""
    actor = _actor_for_workspace(db, actor, organization_id)
    actor_id = _actor_id(actor)
    current = _require_active_lead(
        db,
        lead_id,
        organization_id=organization_id,
    )
    safe_organization_id = int(current["organization_id"])
    require_lead_version(current, expected_row_version)

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
            organization_id=safe_organization_id,
            expected_row_version=expected_row_version,
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
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
              AND row_version = ?
            """,
            (
                actor_id,
                next_status,
                previous_status,
                lead_id,
                safe_organization_id,
                int(updated["row_version"]),
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

    result = get_lead(
        db,
        lead_id,
        organization_id=safe_organization_id,
    )
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
    organization_id: int | None = None,
    expected_row_version: int | None = None,
) -> sqlite3.Row:
    """Place eligible lead research in the workspace-owner review queue."""
    from app.services.lead_research_permissions import (
        can_submit_for_review,
    )

    actor = _actor_for_workspace(db, actor, organization_id)
    actor_id = _actor_id(actor)
    current = _require_active_lead(
        db,
        lead_id,
        organization_id=organization_id,
    )
    safe_organization_id = int(current["organization_id"])
    safe_expected = require_lead_version(current, expected_row_version)

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
                reviewed_by_user_id = NULL,
                reviewed_at = NULL,
                outreach_approved_by_user_id = NULL,
                outreach_approved_at = NULL,
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
              AND research_status = ?
              AND (? IS NULL OR row_version = ?)
            """,
            (
                actor_id,
                lead_id,
                safe_organization_id,
                previous_status,
                safe_expected,
                safe_expected,
            ),
        )
        if cursor.rowcount != 1:
            reloaded = _require_active_lead(
                db,
                lead_id,
                organization_id=safe_organization_id,
            )
            require_lead_version(reloaded, safe_expected)
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

    result = get_lead(
        db,
        lead_id,
        organization_id=safe_organization_id,
    )
    if result is None:
        raise RuntimeError(
            "Submitted lead could not be reloaded"
        )
    return result


def list_research_review_queue(
    db: sqlite3.Connection,
    *,
    organization_id: int | None = None,
) -> list[sqlite3.Row]:
    """Return review-ready leads inside one CRM workspace."""
    safe_organization_id = (
        organization_id_by_slug(db, "mark-agency")
        if organization_id is None
        else int(organization_id)
    )
    if safe_organization_id <= 0:
        raise ValueError("Organization ID must be a positive integer.")
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
        WHERE l.organization_id = ?
          AND l.deleted_at IS NULL
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
        """,
        (safe_organization_id,),
    ).fetchall()


RESEARCH_REVIEW_DECISIONS = frozenset(
    {
        "approved",
        "changes_requested",
        "rejected",
    }
)

RESEARCH_REVIEW_EVENT_TYPES = {
    "approved": "crm_research_approved",
    "changes_requested": (
        "crm_research_changes_requested"
    ),
    "rejected": "crm_research_rejected",
}


def review_research(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    decision: str,
    review_notes: str = "",
    organization_id: int | None = None,
    expected_row_version: int | None = None,
) -> sqlite3.Row:
    """Apply a workspace-owner decision to submitted lead research."""
    from app.services.lead_research_permissions import (
        can_review_research,
    )

    actor = _actor_for_workspace(db, actor, organization_id)
    actor_id = _actor_id(actor)
    current = _require_active_lead(
        db,
        lead_id,
        organization_id=organization_id,
    )
    safe_organization_id = int(current["organization_id"])
    safe_expected = require_lead_version(current, expected_row_version)

    normalized_decision = str(
        decision or ""
    ).strip().casefold()
    normalized_notes = str(
        review_notes or ""
    ).strip()

    if (
        normalized_decision
        not in RESEARCH_REVIEW_DECISIONS
    ):
        raise ValueError(
            "Unsupported research review decision."
        )

    if len(normalized_notes) > 2000:
        raise ValueError(
            "Review notes must be 2000 characters "
            "or fewer."
        )

    if (
        normalized_decision
        in {"changes_requested", "rejected"}
        and not normalized_notes
    ):
        raise ValueError(
            "Review notes are required for this "
            "decision."
        )

    if not can_review_research(actor, current):
        raise LeadPermissionError(
            "You are not allowed to review this "
            "lead research."
        )

    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")

    db.execute(
        "SAVEPOINT lead_research_review"
    )

    try:
        cursor = db.execute(
            """
            UPDATE leads
            SET
                research_status = ?,
                reviewed_by_user_id = ?,
                reviewed_at = CURRENT_TIMESTAMP,
                review_notes = ?,
                outreach_approved_by_user_id = NULL,
                outreach_approved_at = NULL,
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
              AND research_status = (
                  'ready_for_review'
              )
              AND (? IS NULL OR row_version = ?)
            """,
            (
                normalized_decision,
                actor_id,
                normalized_notes,
                lead_id,
                safe_organization_id,
                safe_expected,
                safe_expected,
            ),
        )
        if cursor.rowcount != 1:
            reloaded = _require_active_lead(
                db,
                lead_id,
                organization_id=safe_organization_id,
            )
            require_lead_version(reloaded, safe_expected)
            raise LeadPermissionError(
                "The lead changed before the review "
                "decision could be saved."
            )

        event_type = (
            RESEARCH_REVIEW_EVENT_TYPES[
                normalized_decision
            ]
        )
        note = (
            "Owner research decision: "
            f"{normalized_decision.replace('_', ' ')} "
            f"by user #{actor_id}."
        )
        if normalized_notes:
            note += f" Notes: {normalized_notes}"

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
                ?
            FROM tasks
            WHERE id = ?
            """,
            (
                note,
                event_type,
                current["quest_id"],
            ),
        )

    except BaseException:
        db.execute(
            "ROLLBACK TO SAVEPOINT "
            "lead_research_review"
        )
        db.execute(
            "RELEASE SAVEPOINT "
            "lead_research_review"
        )
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute(
            "RELEASE SAVEPOINT "
            "lead_research_review"
        )

    result = get_lead(
        db,
        lead_id,
        organization_id=safe_organization_id,
    )
    if result is None:
        raise RuntimeError(
            "Reviewed lead could not be reloaded"
        )
    return result
