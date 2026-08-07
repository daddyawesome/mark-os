from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

from app.db.organizations import organization_id_by_slug
from app.db.lead_activities import (
    ACTIVITY_TYPES,
    CHANNELS,
    RESPONSE_STATUSES,
)
from app.services.access_control import (
    has_crm_owner_authority,
    is_lead_sourcer,
)
from app.services.lead_research_permissions import can_view_lead
from app.services.leads import get_lead
from app.services.workspace_context import (
    load_crm_actor_for_workspace,
    require_workspace_membership,
)


Record = Mapping[str, Any] | sqlite3.Row

MAX_MESSAGE_SUMMARY_LENGTH = 1_000
MAX_NOTES_LENGTH = 5_000
MAX_CORRECTION_REASON_LENGTH = 1_000
MAX_ACTIVITY_LIST_LIMIT = 500

CRM_ACTIVITY_ROLES = frozenset(
    {
        "owner",
        "lead_sourcer",
        "relationship_manager",
    }
)

LEAD_SOURCER_ACTIVITY_TYPES = frozenset(
    {
        "research_started",
        "research_completed",
        "submitted_for_review",
    }
)

# Relationship Managers can read activity history for leads in their existing
# CRM scope. They do not receive outbound-activity creation permission here.
# Phase 6.13 adds the separate, narrow, revocable delegated-outreach gate.
RELATIONSHIP_MANAGER_ACTIVITY_TYPES = frozenset()

_UNSET = object()


class LeadActivityPermissionError(PermissionError):
    """Raised when an authenticated CRM actor is not allowed to act."""


class LeadActivityNotFoundError(LookupError):
    """Raised for missing and non-visible lead/activity records alike."""


def _positive_id(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _record_value(
    record: Record | None,
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
    if actor is None:
        raise LeadActivityPermissionError(
            "An authenticated CRM user is required."
        )
    try:
        return _positive_id(_record_value(actor, "id"), "Actor ID")
    except ValueError as exc:
        raise LeadActivityPermissionError(
            "The authenticated CRM user is invalid."
        ) from exc


def _load_active_actor(
    db: sqlite3.Connection,
    actor: Record | None,
    *,
    organization_id: int | None = None,
) -> dict[str, Any]:
    actor_id = _actor_id(actor)
    row = db.execute(
        """
        SELECT id, username, display_name, role, active
        FROM users
        WHERE id = ?
          AND active = 1
        """,
        (actor_id,),
    ).fetchone()
    if row is None or row["role"] not in CRM_ACTIVITY_ROLES:
        raise LeadActivityPermissionError(
            "An active CRM role is required."
        )
    database_actor = dict(row)
    if organization_id is not None:
        try:
            return load_crm_actor_for_workspace(
                db,
                database_actor,
                organization_id,
            )
        except PermissionError as exc:
            raise LeadActivityPermissionError(
                "CRM workspace membership is required."
            ) from exc
    return database_actor


def _active_crm_user_id(
    db: sqlite3.Connection,
    value: int | None,
    field_name: str,
    *,
    organization_id: int | None = None,
) -> int | None:
    if value is None:
        return None
    user_id = _positive_id(value, field_name)
    if organization_id is None:
        row = db.execute(
            """
            SELECT id
            FROM users
            WHERE id = ?
              AND active = 1
              AND role IN (
                  'owner',
                  'lead_sourcer',
                  'relationship_manager'
              )
            """,
            (user_id,),
        ).fetchone()
    else:
        row = db.execute(
            """
            SELECT users.id
            FROM users
            JOIN organization_memberships AS membership
              ON membership.user_id = users.id
             AND membership.organization_id = ?
            WHERE users.id = ?
              AND users.active = 1
              AND membership.active = 1
              AND users.role IN (
                  'owner',
                  'lead_sourcer',
                  'relationship_manager'
              )
            """,
            (organization_id, user_id),
        ).fetchone()
    if row is None:
        raise ValueError(
            f"{field_name} must reference an active CRM user."
        )
    return user_id


def _required_text(
    value: Any,
    field_name: str,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean:
        raise ValueError(f"{field_name} is required.")
    if len(clean) > maximum:
        raise ValueError(
            f"{field_name} must be {maximum} characters or fewer."
        )
    return clean


def _optional_text(
    value: Any,
    field_name: str,
    maximum: int,
) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(clean) > maximum:
        raise ValueError(
            f"{field_name} must be {maximum} characters or fewer."
        )
    return clean


def _choice(
    value: Any,
    field_name: str,
    allowed: tuple[str, ...],
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = value.strip().casefold()
    if clean not in allowed:
        raise ValueError(f"Unsupported {field_name.lower()}.")
    return clean


def _normalize_activity_at(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Activity date and time must be text.")
    clean = value.strip()
    if not clean or ("T" not in clean and " " not in clean):
        raise ValueError(
            "Activity date and time must use ISO 8601 date-time format."
        )

    parse_value = clean[:-1] + "+00:00" if clean.endswith(("Z", "z")) else clean
    try:
        parsed = datetime.fromisoformat(parse_value)
    except ValueError as exc:
        raise ValueError(
            "Activity date and time must use ISO 8601 date-time format."
        ) from exc

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.replace(microsecond=0).isoformat(sep=" ")


def _normalize_follow_up_date(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Next follow-up date must be text.")
    clean = value.strip()
    if not clean:
        return None
    try:
        normalized = date.fromisoformat(clean).isoformat()
    except ValueError as exc:
        raise ValueError("Next follow-up date must use YYYY-MM-DD.") from exc
    if normalized != clean:
        raise ValueError("Next follow-up date must use YYYY-MM-DD.")
    return normalized


def _allowed_activity_types(
    actor: Record,
    lead: Record,
) -> frozenset[str]:
    if not can_view_lead(actor, lead):
        return frozenset()
    if has_crm_owner_authority(actor):
        return frozenset(ACTIVITY_TYPES)
    if is_lead_sourcer(actor):
        return LEAD_SOURCER_ACTIVITY_TYPES
    return RELATIONSHIP_MANAGER_ACTIVITY_TYPES


def _require_visible_lead(
    db: sqlite3.Connection,
    actor: Record,
    lead_id: int,
    *,
    organization_id: int | None = None,
) -> sqlite3.Row:
    safe_lead_id = _positive_id(lead_id, "Lead ID")
    if organization_id is not None:
        try:
            require_workspace_membership(
                db,
                int(actor["id"]),
                organization_id,
            )
        except PermissionError as exc:
            raise LeadActivityNotFoundError("Lead not found.") from exc
    lead = get_lead(
        db,
        safe_lead_id,
        organization_id=organization_id,
    )
    if lead is None or not can_view_lead(actor, lead):
        raise LeadActivityNotFoundError("Lead not found.")
    return lead


def _activity_select() -> str:
    return """
        SELECT
            a.*,
            creator.username AS created_by_username,
            creator.display_name AS created_by_name,
            performer.username AS performed_by_username,
            performer.display_name AS performed_by_name,
            responsible.username AS responsible_username,
            responsible.display_name AS responsible_name,
            corrector.username AS corrected_by_username,
            corrector.display_name AS corrected_by_name
        FROM lead_activities AS a
        JOIN users AS creator
          ON creator.id = a.created_by_user_id
        JOIN users AS performer
          ON performer.id = a.performed_by_user_id
        LEFT JOIN users AS responsible
          ON responsible.id = a.responsible_user_id
        LEFT JOIN users AS corrector
          ON corrector.id = a.corrected_by_user_id
    """


def _activity_row(
    db: sqlite3.Connection,
    activity_id: int,
    *,
    include_deleted: bool,
) -> sqlite3.Row | None:
    safe_activity_id = _positive_id(activity_id, "Activity ID")
    deleted_condition = "" if include_deleted else "AND a.deleted_at IS NULL"
    return db.execute(
        f"""
        {_activity_select()}
        WHERE a.id = ?
          {deleted_condition}
        """,
        (safe_activity_id,),
    ).fetchone()


def _require_visible_activity(
    db: sqlite3.Connection,
    actor: Record,
    activity_id: int,
    *,
    include_deleted: bool = False,
    organization_id: int | None = None,
) -> sqlite3.Row:
    activity = _activity_row(
        db,
        activity_id,
        include_deleted=include_deleted,
    )
    if activity is None:
        raise LeadActivityNotFoundError("Lead activity not found.")
    _require_visible_lead(
        db,
        actor,
        int(activity["lead_id"]),
        organization_id=organization_id,
    )
    return activity


def _normalized_values(
    db: sqlite3.Connection,
    *,
    actor: Record,
    lead: Record,
    activity_type: Any,
    activity_at: Any,
    channel: Any,
    message_summary: Any,
    notes: Any,
    performed_by_user_id: int | None,
    responsible_user_id: int | None,
    response_status: Any,
    next_follow_up_date: Any,
    organization_id: int | None = None,
) -> dict[str, Any]:
    clean_type = _choice(activity_type, "Activity type", ACTIVITY_TYPES)
    allowed_types = _allowed_activity_types(actor, lead)
    if clean_type not in allowed_types:
        raise LeadActivityPermissionError(
            "You are not allowed to record this activity type."
        )

    clean_channel = _choice(channel, "Channel", CHANNELS)
    clean_response = _choice(
        response_status,
        "Response status",
        RESPONSE_STATUSES,
    )
    actor_id = int(actor["id"])

    performer_id = (
        actor_id
        if performed_by_user_id is None
        else _active_crm_user_id(
            db,
            performed_by_user_id,
            "Performed-by user ID",
            organization_id=organization_id,
        )
    )
    if performer_id != actor_id and not has_crm_owner_authority(actor):
        raise LeadActivityPermissionError(
            "Only the Owner can attribute an activity to another performer."
        )

    responsible_id = _active_crm_user_id(
        db,
        responsible_user_id,
        "Responsible user ID",
        organization_id=organization_id,
    )
    clean_follow_up = _normalize_follow_up_date(next_follow_up_date)
    if clean_follow_up is not None and responsible_id is None:
        raise ValueError(
            "A responsible CRM user is required when a follow-up date is set."
        )

    if not has_crm_owner_authority(actor) and clean_channel != "internal":
        raise LeadActivityPermissionError(
            "Staff activity records are internal until delegated outreach "
            "permission is implemented."
        )

    return {
        "activity_type": clean_type,
        "activity_at": _normalize_activity_at(activity_at),
        "channel": clean_channel,
        "message_summary": _required_text(
            message_summary,
            "Message summary",
            MAX_MESSAGE_SUMMARY_LENGTH,
        ),
        "notes": _optional_text(notes, "Notes", MAX_NOTES_LENGTH),
        "performed_by_user_id": performer_id,
        "responsible_user_id": responsible_id,
        "response_status": clean_response,
        "next_follow_up_date": clean_follow_up,
    }


@contextmanager
def _write_unit(db: sqlite3.Connection) -> Iterator[None]:
    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")
    else:
        db.execute("UPDATE lead_activities SET id = id WHERE 0")

    db.execute("SAVEPOINT lead_activity_service_write")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK TO SAVEPOINT lead_activity_service_write")
        db.execute("RELEASE SAVEPOINT lead_activity_service_write")
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute("RELEASE SAVEPOINT lead_activity_service_write")



def list_active_activity_users(
    db: sqlite3.Connection,
    *,
    actor: Record,
    organization_id: int | None = None,
) -> list[sqlite3.Row]:
    """Return active CRM users who belong to the selected workspace."""
    safe_organization_id = (
        organization_id_by_slug(db, "mark-agency")
        if organization_id is None
        else _positive_id(organization_id, "Organization ID")
    )
    database_actor = _load_active_actor(
        db,
        actor,
        organization_id=safe_organization_id,
    )
    if organization_id is not None:
        try:
            require_workspace_membership(
                db,
                int(database_actor["id"]),
                safe_organization_id,
            )
        except PermissionError as exc:
            raise LeadActivityPermissionError(
                "CRM workspace membership is required."
            ) from exc
    return db.execute(
        """
        SELECT
            id,
            username,
            display_name,
            role
        FROM users
        JOIN organization_memberships AS membership
          ON membership.user_id = users.id
         AND membership.organization_id = ?
        WHERE users.active = 1
          AND membership.active = 1
          AND role IN (
              'owner',
              'lead_sourcer',
              'relationship_manager'
          )
        ORDER BY
            CASE role
                WHEN 'owner' THEN 1
                WHEN 'lead_sourcer' THEN 2
                WHEN 'relationship_manager' THEN 3
                ELSE 4
            END,
            display_name COLLATE NOCASE,
            id
        """,
        (safe_organization_id,),
    ).fetchall()
def create_activity(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    activity_type: str,
    activity_at: str,
    message_summary: str,
    channel: str = "internal",
    notes: str = "",
    performed_by_user_id: int | None = None,
    responsible_user_id: int | None = None,
    response_status: str = "not_applicable",
    next_follow_up_date: str | None = None,
    organization_id: int | None = None,
) -> sqlite3.Row:
    """Append an auditable activity for one visible lead."""
    database_actor = _load_active_actor(db, actor, organization_id=organization_id)
    lead = _require_visible_lead(
        db,
        database_actor,
        lead_id,
        organization_id=organization_id,
    )
    values = _normalized_values(
        db,
        actor=database_actor,
        lead=lead,
        activity_type=activity_type,
        activity_at=activity_at,
        channel=channel,
        message_summary=message_summary,
        notes=notes,
        performed_by_user_id=performed_by_user_id,
        responsible_user_id=responsible_user_id,
        response_status=response_status,
        next_follow_up_date=next_follow_up_date,
        organization_id=organization_id,
    )

    with _write_unit(db):
        cursor = db.execute(
            """
            INSERT INTO lead_activities (
                lead_id,
                activity_type,
                activity_at,
                channel,
                message_summary,
                notes,
                created_by_user_id,
                performed_by_user_id,
                responsible_user_id,
                response_status,
                next_follow_up_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(lead["id"]),
                values["activity_type"],
                values["activity_at"],
                values["channel"],
                values["message_summary"],
                values["notes"],
                int(database_actor["id"]),
                values["performed_by_user_id"],
                values["responsible_user_id"],
                values["response_status"],
                values["next_follow_up_date"],
            ),
        )
        activity_id = int(cursor.lastrowid)

    created = _activity_row(db, activity_id, include_deleted=False)
    if created is None:
        raise RuntimeError("Created lead activity could not be reloaded.")
    return created


def list_lead_activities(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    include_deleted: bool = False,
    limit: int = 100,
    organization_id: int | None = None,
) -> list[sqlite3.Row]:
    database_actor = _load_active_actor(db, actor, organization_id=organization_id)
    lead = _require_visible_lead(
        db,
        database_actor,
        lead_id,
        organization_id=organization_id,
    )
    if include_deleted and not has_crm_owner_authority(database_actor):
        raise LeadActivityPermissionError(
            "Only the Owner can view deleted activity records."
        )
    safe_limit = _positive_id(limit, "Activity list limit")
    if safe_limit > MAX_ACTIVITY_LIST_LIMIT:
        raise ValueError(
            f"Activity list limit cannot exceed {MAX_ACTIVITY_LIST_LIMIT}."
        )

    deleted_condition = "" if include_deleted else "AND a.deleted_at IS NULL"
    return db.execute(
        f"""
        {_activity_select()}
        WHERE a.lead_id = ?
          {deleted_condition}
        ORDER BY a.activity_at DESC, a.id DESC
        LIMIT ?
        """,
        (int(lead["id"]), safe_limit),
    ).fetchall()


def get_activity(
    db: sqlite3.Connection,
    activity_id: int,
    *,
    actor: Record,
    include_deleted: bool = False,
    organization_id: int | None = None,
) -> sqlite3.Row:
    database_actor = _load_active_actor(db, actor, organization_id=organization_id)
    if include_deleted and not has_crm_owner_authority(database_actor):
        raise LeadActivityNotFoundError("Lead activity not found.")
    return _require_visible_activity(
        db,
        database_actor,
        activity_id,
        include_deleted=include_deleted,
        organization_id=organization_id,
    )


def _can_correct(
    actor: Record,
    lead: Record,
    activity: Record,
) -> bool:
    if has_crm_owner_authority(actor):
        return True
    return (
        is_lead_sourcer(actor)
        and int(activity["created_by_user_id"]) == int(actor["id"])
        and str(activity["activity_type"]) in _allowed_activity_types(actor, lead)
    )


def correct_activity(
    db: sqlite3.Connection,
    activity_id: int,
    *,
    actor: Record,
    correction_reason: str,
    activity_type: str | object = _UNSET,
    activity_at: str | object = _UNSET,
    channel: str | object = _UNSET,
    message_summary: str | object = _UNSET,
    notes: str | object = _UNSET,
    performed_by_user_id: int | None | object = _UNSET,
    responsible_user_id: int | None | object = _UNSET,
    response_status: str | object = _UNSET,
    next_follow_up_date: str | None | object = _UNSET,
    organization_id: int | None = None,
) -> sqlite3.Row:
    """Correct an activity while preserving its original author."""
    database_actor = _load_active_actor(db, actor, organization_id=organization_id)
    current = _require_visible_activity(
        db,
        database_actor,
        activity_id,
        organization_id=organization_id,
    )
    lead = _require_visible_lead(
        db,
        database_actor,
        int(current["lead_id"]),
        organization_id=organization_id,
    )
    if not _can_correct(database_actor, lead, current):
        raise LeadActivityPermissionError(
            "You are not allowed to correct this activity."
        )

    reason = _required_text(
        correction_reason,
        "Correction reason",
        MAX_CORRECTION_REASON_LENGTH,
    )
    supplied = {
        "activity_type": activity_type,
        "activity_at": activity_at,
        "channel": channel,
        "message_summary": message_summary,
        "notes": notes,
        "performed_by_user_id": performed_by_user_id,
        "responsible_user_id": responsible_user_id,
        "response_status": response_status,
        "next_follow_up_date": next_follow_up_date,
    }
    if all(value is _UNSET for value in supplied.values()):
        raise ValueError("At least one activity field must be corrected.")

    values = _normalized_values(
        db,
        actor=database_actor,
        lead=lead,
        activity_type=(
            current["activity_type"]
            if activity_type is _UNSET
            else activity_type
        ),
        activity_at=(
            current["activity_at"] if activity_at is _UNSET else activity_at
        ),
        channel=current["channel"] if channel is _UNSET else channel,
        message_summary=(
            current["message_summary"]
            if message_summary is _UNSET
            else message_summary
        ),
        notes=current["notes"] if notes is _UNSET else notes,
        performed_by_user_id=(
            int(current["performed_by_user_id"])
            if performed_by_user_id is _UNSET
            else performed_by_user_id
        ),
        responsible_user_id=(
            current["responsible_user_id"]
            if responsible_user_id is _UNSET
            else responsible_user_id
        ),
        response_status=(
            current["response_status"]
            if response_status is _UNSET
            else response_status
        ),
        next_follow_up_date=(
            current["next_follow_up_date"]
            if next_follow_up_date is _UNSET
            else next_follow_up_date
        ),
        organization_id=organization_id,
    )

    if not any(values[field] != current[field] for field in values):
        raise ValueError("The correction does not change any activity field.")

    with _write_unit(db):
        cursor = db.execute(
            """
            UPDATE lead_activities
            SET
                activity_type = ?,
                activity_at = ?,
                channel = ?,
                message_summary = ?,
                notes = ?,
                performed_by_user_id = ?,
                responsible_user_id = ?,
                response_status = ?,
                next_follow_up_date = ?,
                corrected_by_user_id = ?,
                correction_reason = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND deleted_at IS NULL
            """,
            (
                values["activity_type"],
                values["activity_at"],
                values["channel"],
                values["message_summary"],
                values["notes"],
                values["performed_by_user_id"],
                values["responsible_user_id"],
                values["response_status"],
                values["next_follow_up_date"],
                int(database_actor["id"]),
                reason,
                int(current["id"]),
            ),
        )
        if cursor.rowcount != 1:
            raise LeadActivityNotFoundError("Lead activity not found.")

    corrected = _activity_row(db, int(current["id"]), include_deleted=False)
    if corrected is None:
        raise RuntimeError("Corrected lead activity could not be reloaded.")
    return corrected


def soft_delete_activity(
    db: sqlite3.Connection,
    activity_id: int,
    *,
    actor: Record,
    correction_reason: str,
    organization_id: int | None = None,
) -> sqlite3.Row:
    database_actor = _load_active_actor(db, actor, organization_id=organization_id)
    current = _require_visible_activity(
        db,
        database_actor,
        activity_id,
        organization_id=organization_id,
    )
    lead = _require_visible_lead(
        db,
        database_actor,
        int(current["lead_id"]),
        organization_id=organization_id,
    )
    if not _can_correct(database_actor, lead, current):
        raise LeadActivityPermissionError(
            "You are not allowed to delete this activity."
        )

    reason = _required_text(
        correction_reason,
        "Correction reason",
        MAX_CORRECTION_REASON_LENGTH,
    )
    with _write_unit(db):
        cursor = db.execute(
            """
            UPDATE lead_activities
            SET
                deleted_at = CURRENT_TIMESTAMP,
                corrected_by_user_id = ?,
                correction_reason = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND deleted_at IS NULL
            """,
            (
                int(database_actor["id"]),
                reason,
                int(current["id"]),
            ),
        )
        if cursor.rowcount != 1:
            raise LeadActivityNotFoundError("Lead activity not found.")

    deleted = _activity_row(db, int(current["id"]), include_deleted=True)
    if deleted is None:
        raise RuntimeError("Deleted lead activity could not be reloaded.")
    return deleted


def restore_activity(
    db: sqlite3.Connection,
    activity_id: int,
    *,
    actor: Record,
    correction_reason: str,
    organization_id: int | None = None,
) -> sqlite3.Row:
    database_actor = _load_active_actor(db, actor, organization_id=organization_id)
    if not has_crm_owner_authority(database_actor):
        raise LeadActivityPermissionError(
            "Workspace owner authority is required to restore an activity."
        )

    current = _require_visible_activity(
        db,
        database_actor,
        activity_id,
        include_deleted=True,
        organization_id=organization_id,
    )
    if current["deleted_at"] is None:
        raise ValueError("Lead activity is not deleted.")

    reason = _required_text(
        correction_reason,
        "Correction reason",
        MAX_CORRECTION_REASON_LENGTH,
    )
    with _write_unit(db):
        cursor = db.execute(
            """
            UPDATE lead_activities
            SET
                deleted_at = NULL,
                corrected_by_user_id = ?,
                correction_reason = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND deleted_at IS NOT NULL
            """,
            (
                int(database_actor["id"]),
                reason,
                int(current["id"]),
            ),
        )
        if cursor.rowcount != 1:
            raise LeadActivityNotFoundError("Lead activity not found.")

    restored = _activity_row(db, int(current["id"]), include_deleted=False)
    if restored is None:
        raise RuntimeError("Restored lead activity could not be reloaded.")
    return restored
