from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from app.db.lead_research import RESEARCH_STATUSES
from app.services.access_control import (
    has_crm_owner_authority,
    is_lead_sourcer,
    is_owner,
    is_relationship_manager,
)
from app.services.leads import PIPELINE_STATUSES


Record = Mapping[str, Any] | sqlite3.Row

SOURCER_RESEARCH_EDIT_FIELDS = frozenset(
    {
        "company",
        "contact_person",
        "job_title",
        "source",
        "source_url",
        "problem_opportunity",
        "why_mark_fits",
        "next_action",
        "next_action_due_date",
        "notes",
    }
)

OWNER_GENERAL_EDIT_FIELDS = frozenset(
    set(SOURCER_RESEARCH_EDIT_FIELDS)
    | {
        "priority",
        "assigned_to_user_id",
    }
)

SYSTEM_MANAGED_FIELDS = frozenset(
    {
        "id",
        "quest_id",
        "created_by_user_id",
        "business_development_owner_user_id",
        "researched_by_user_id",
        "research_status",
        "submitted_for_review_at",
        "reviewed_by_user_id",
        "reviewed_at",
        "review_notes",
        "outreach_approved_by_user_id",
        "outreach_approved_at",
        "request_key",
        "request_fingerprint",
        "dedupe_key",
        "pipeline_status",
        "created_at",
        "updated_at",
        "deleted_at",
    }
)

SOURCER_EDITABLE_RESEARCH_STATUSES = frozenset(
    {
        "draft",
        "researching",
        "changes_requested",
    }
)

SOURCER_RESEARCH_TRANSITIONS = {
    "draft": frozenset(
        {
            "researching",
            "ready_for_review",
        }
    ),
    "researching": frozenset(
        {
            "ready_for_review",
        }
    ),
    "changes_requested": frozenset(
        {
            "researching",
            "ready_for_review",
        }
    ),
}


class LeadPermissionError(PermissionError):
    """Raised when a CRM actor attempts a forbidden lead action."""


def _value(
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


def _positive_actor_id(
    user: Record | None,
) -> int | None:
    value = _value(user, "id")

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        return None

    return value


def _normalized_research_status(
    lead: Record | None,
) -> str:
    return str(
        _value(lead, "research_status", "")
        or ""
    ).strip().casefold()


def _lead_is_active(
    lead: Record | None,
) -> bool:
    return (
        lead is not None
        and _value(lead, "deleted_at") is None
    )


def _actor_matches_lead(
    user: Record | None,
    lead: Record | None,
) -> bool:
    actor_id = _positive_actor_id(user)

    if actor_id is None or lead is None:
        return False

    related_user_ids = {
        _value(lead, "created_by_user_id"),
        _value(lead, "assigned_to_user_id"),
        _value(lead, "researched_by_user_id"),
    }

    return actor_id in related_user_ids


def can_view_lead(
    user: Record | None,
    lead: Record | None,
) -> bool:
    if not _lead_is_active(lead):
        return False

    if has_crm_owner_authority(user):
        return True

    if is_lead_sourcer(user):
        return _actor_matches_lead(user, lead)

    if is_relationship_manager(user):
        actor_id = _positive_actor_id(user)
        return actor_id in {
            _value(lead, "created_by_user_id"),
            _value(lead, "business_development_owner_user_id"),
        }

    return False


def editable_fields_for(
    user: Record | None,
    lead: Record | None,
) -> frozenset[str]:
    if not _lead_is_active(lead):
        return frozenset()

    if has_crm_owner_authority(user):
        return OWNER_GENERAL_EDIT_FIELDS

    if (
        is_lead_sourcer(user)
        and _actor_matches_lead(user, lead)
        and _normalized_research_status(lead)
        in SOURCER_EDITABLE_RESEARCH_STATUSES
    ):
        return SOURCER_RESEARCH_EDIT_FIELDS

    return frozenset()


def can_edit_research(
    user: Record | None,
    lead: Record | None,
) -> bool:
    return bool(editable_fields_for(user, lead))


def forbidden_edit_fields(
    user: Record | None,
    lead: Record | None,
    requested_fields: Iterable[str],
) -> frozenset[str]:
    allowed = editable_fields_for(user, lead)
    normalized_requested = {
        str(field).strip()
        for field in requested_fields
        if str(field).strip()
    }

    return frozenset(
        normalized_requested - set(allowed)
    )


def require_edit_fields(
    user: Record | None,
    lead: Record | None,
    requested_fields: Iterable[str],
) -> frozenset[str]:
    requested = frozenset(
        str(field).strip()
        for field in requested_fields
        if str(field).strip()
    )
    forbidden = forbidden_edit_fields(
        user,
        lead,
        requested,
    )

    if forbidden:
        raise LeadPermissionError(
            "You are not allowed to edit these lead "
            f"fields: {', '.join(sorted(forbidden))}"
        )

    if not requested:
        raise ValueError(
            "At least one lead field must be supplied."
        )

    return requested


def can_transition_research_status(
    user: Record | None,
    lead: Record | None,
    target_status: str,
) -> bool:
    if not _lead_is_active(lead):
        return False

    normalized_target = (
        str(target_status or "")
        .strip()
        .casefold()
    )
    if normalized_target not in RESEARCH_STATUSES:
        return False

    current_status = _normalized_research_status(
        lead
    )
    if current_status == normalized_target:
        return can_view_lead(user, lead)

    if has_crm_owner_authority(user):
        return True

    if (
        not is_lead_sourcer(user)
        or not _actor_matches_lead(user, lead)
    ):
        return False

    return normalized_target in (
        SOURCER_RESEARCH_TRANSITIONS.get(
            current_status,
            frozenset(),
        )
    )


def require_research_status_transition(
    user: Record | None,
    lead: Record | None,
    target_status: str,
) -> str:
    normalized_target = (
        str(target_status or "")
        .strip()
        .casefold()
    )

    if normalized_target not in RESEARCH_STATUSES:
        raise ValueError(
            "Unsupported research status."
        )

    if not can_transition_research_status(
        user,
        lead,
        normalized_target,
    ):
        raise LeadPermissionError(
            "You are not allowed to perform this "
            "research-status transition."
        )

    return normalized_target


def can_submit_for_review(
    user: Record | None,
    lead: Record | None,
) -> bool:
    return (
        _normalized_research_status(lead)
        in {
            "draft",
            "researching",
            "changes_requested",
        }
        and can_transition_research_status(
            user,
            lead,
            "ready_for_review",
        )
    )


def can_review_research(
    user: Record | None,
    lead: Record | None,
) -> bool:
    return (
        has_crm_owner_authority(user)
        and _lead_is_active(lead)
        and _normalized_research_status(lead)
        == "ready_for_review"
    )


def can_approve_outreach(
    user: Record | None,
    lead: Record | None,
) -> bool:
    return (
        has_crm_owner_authority(user)
        and _lead_is_active(lead)
        and _normalized_research_status(lead)
        == "approved"
    )


def can_reassign_lead(
    user: Record | None,
    lead: Record | None,
) -> bool:
    return (
        has_crm_owner_authority(user)
        and _lead_is_active(lead)
    )


def can_change_pipeline(
    user: Record | None,
    lead: Record | None,
    target_status: str,
) -> bool:
    normalized_target = (
        str(target_status or "")
        .strip()
        .casefold()
    )

    return (
        has_crm_owner_authority(user)
        and _lead_is_active(lead)
        and normalized_target in PIPELINE_STATUSES
    )


def require_pipeline_change(
    user: Record | None,
    lead: Record | None,
    target_status: str,
) -> str:
    normalized_target = (
        str(target_status or "")
        .strip()
        .casefold()
    )

    if normalized_target not in PIPELINE_STATUSES:
        raise ValueError(
            "Unsupported lead pipeline status."
        )

    if not can_change_pipeline(
        user,
        lead,
        normalized_target,
    ):
        raise LeadPermissionError(
            "Only the Owner can change a lead's "
            "pipeline status."
        )

    return normalized_target


def can_soft_delete_lead(
    user: Record | None,
    lead: Record | None,
) -> bool:
    return (
        has_crm_owner_authority(user)
        and _lead_is_active(lead)
    )


def can_permanently_delete_lead(
    user: Record | None,
    lead: Record | None,
) -> bool:
    # Permanent purge is intentionally unavailable in
    # the normal MARK-OS application workflow.
    return False


def can_view_private_finance(
    user: Record | None,
) -> bool:
    return is_owner(user)
