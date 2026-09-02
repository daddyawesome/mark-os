from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any, Iterator

from app.db.lead_activities import (
    CHANNELS,
    CONTACT_ACTIVITY_TYPES,
    CONTACT_CHANNELS,
    CONTACT_RESPONSE_STATUSES,
    RESPONSE_STATUSES,
)
from app.services.lead_activities import (
    create_activity as create_lead_activity,
)

from app.services.lead_research_permissions import (
    LeadPermissionError,
    can_approve_outreach,
    require_pipeline_change,
)
from app.services.leads import (
    get_lead,
    require_lead_version,
    update_lead,
    update_lead_pipeline,
)
from app.services.workspace_context import load_crm_actor_for_workspace


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



def _required_contact_text(
    value: str | None,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LeadPipelineRuleError(
            "The Contacted transition requires a complete contact audit. "
            f"{field_name} is required."
        )
    return value.strip()


def _required_contact_user_id(
    value: int | None,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise LeadPipelineRuleError(
            "The Contacted transition requires a responsible CRM user."
        )
    return value


def _append_contact_activity(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    actor_id: int,
    contact_activity_type: str | None,
    contact_activity_at: str | None,
    contact_channel: str | None,
    contact_message_summary: str | None,
    contact_notes: str | None,
    contact_responsible_user_id: int | None,
    contact_response_status: str | None,
    contact_next_follow_up_date: str | None,
    organization_id: int,
) -> sqlite3.Row:
    activity_type = _required_contact_text(
        contact_activity_type,
        "Activity type",
    ).casefold()
    if activity_type not in CONTACT_ACTIVITY_TYPES:
        raise LeadPipelineRuleError(
            "The Contacted transition requires an outbound "
            "contact activity type."
        )

    channel = _required_contact_text(
        contact_channel,
        "Contact channel",
    ).casefold()
    if channel not in CONTACT_CHANNELS:
        raise LeadPipelineRuleError(
            "The Contacted transition requires an external contact channel."
        )

    response_status = _required_contact_text(
        contact_response_status,
        "Response status",
    ).casefold()
    if response_status not in CONTACT_RESPONSE_STATUSES:
        raise LeadPipelineRuleError(
            "The Contacted transition requires a current response status."
        )

    responsible_user_id = _required_contact_user_id(
        contact_responsible_user_id
    )
    activity_at = _required_contact_text(
        contact_activity_at,
        "Date and time contacted",
    )
    message_summary = _required_contact_text(
        contact_message_summary,
        "Message summary",
    )
    next_follow_up_date = _required_contact_text(
        contact_next_follow_up_date,
        "Next follow-up date",
    )

    return create_lead_activity(
        db,
        lead_id,
        actor=actor,
        activity_type=activity_type,
        activity_at=activity_at,
        channel=channel,
        message_summary=message_summary,
        notes=(contact_notes or "").strip(),
        performed_by_user_id=actor_id,
        responsible_user_id=responsible_user_id,
        response_status=response_status,
        next_follow_up_date=next_follow_up_date,
        organization_id=organization_id,
    )
def approve_outreach(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    organization_id: int | None = None,
    expected_row_version: int | None = None,
) -> sqlite3.Row:
    """Record workspace-owner approval before first outreach."""
    actor = _actor_for_workspace(db, actor, organization_id)
    actor_id = _actor_id(actor)

    with _workflow_write(
        db,
        "lead_outreach_approval",
    ):
        current = _require_active_lead(
            db,
            lead_id,
            organization_id=organization_id,
        )
        safe_organization_id = int(current["organization_id"])
        safe_expected = require_lead_version(current, expected_row_version)

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
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
              AND research_status = 'approved'
              AND outreach_approved_by_user_id IS NULL
              AND outreach_approved_at IS NULL
              AND (? IS NULL OR row_version = ?)
            """,
            (
                actor_id,
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
            if (
                safe_expected is not None
                and int(reloaded["row_version"]) != safe_expected
            ):
                require_lead_version(reloaded, safe_expected)
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

    approved = get_lead(
        db,
        lead_id,
        organization_id=safe_organization_id,
    )
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
    contact_activity_type: str | None = None,
    contact_activity_at: str | None = None,
    contact_channel: str | None = None,
    contact_message_summary: str | None = None,
    contact_notes: str | None = None,
    contact_responsible_user_id: int | None = None,
    contact_response_status: str | None = None,
    contact_next_follow_up_date: str | None = None,
    organization_id: int | None = None,
    expected_row_version: int | None = None,
) -> sqlite3.Row:
    """Apply an owner-authorized transition inside one workspace."""
    actor = _actor_for_workspace(db, actor, organization_id)
    actor_id = _actor_id(actor)
    with _workflow_write(
        db,
        "lead_pipeline_transition",
    ):
        current = _require_active_lead(
            db,
            lead_id,
            organization_id=organization_id,
        )
        safe_organization_id = int(current["organization_id"])
        require_lead_version(current, expected_row_version)
        target_status = require_pipeline_change(
            actor,
            current,
            pipeline_status,
        )
        _validate_major_transition(
            current,
            target_status,
        )

        current_status = str(
            current["pipeline_status"] or ""
        ).strip().casefold()
        if (
            target_status == "contacted"
            and current_status != "contacted"
        ):
            _append_contact_activity(
                db,
                lead_id,
                actor=actor,
                actor_id=actor_id,
                contact_activity_type=contact_activity_type,
                contact_activity_at=contact_activity_at,
                contact_channel=contact_channel,
                contact_message_summary=contact_message_summary,
                contact_notes=contact_notes,
                contact_responsible_user_id=(
                    contact_responsible_user_id
                ),
                contact_response_status=(
                    contact_response_status
                ),
                contact_next_follow_up_date=(
                    contact_next_follow_up_date
                ),
                organization_id=safe_organization_id,
            )

        return update_lead_pipeline(
            db,
            lead_id,
            pipeline_status=target_status,
            organization_id=safe_organization_id,
            expected_row_version=expected_row_version,
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
    organization_id: int | None = None,
    expected_row_version: int | None = None,
) -> sqlite3.Row:
    """Protect full owner-authority edits inside one CRM workspace."""
    actor = _actor_for_workspace(db, actor, organization_id)
    _actor_id(actor)

    with _workflow_write(
        db,
        "lead_owner_full_edit",
    ):
        current = _require_active_lead(
            db,
            lead_id,
            organization_id=organization_id,
        )
        safe_organization_id = int(current["organization_id"])
        require_lead_version(current, expected_row_version)
        target_status = require_pipeline_change(
            actor,
            current,
            pipeline_status,
        )
        _validate_major_transition(
            current,
            target_status,
        )
        current_status = str(
            current["pipeline_status"] or ""
        ).strip().casefold()
        if (
            target_status == "contacted"
            and current_status != "contacted"
        ):
            raise LeadPipelineRuleError(
                "Use the dedicated Contacted transition "
                "so the required contact activity is saved "
                "atomically."
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
            organization_id=safe_organization_id,
            expected_row_version=expected_row_version,
        )
