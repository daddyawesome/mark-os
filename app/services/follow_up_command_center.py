from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.services.lead_work_queues import list_visible_leads


Record = Mapping[str, Any] | sqlite3.Row
MANILA_TIMEZONE = ZoneInfo("Asia/Manila")
CRM_ROLES = frozenset(
    {
        "owner",
        "lead_sourcer",
        "relationship_manager",
    }
)
ACTIVE_PIPELINE_STATUSES = frozenset(
    {
        "new",
        "reviewed",
        "contacted",
        "replied",
        "meeting",
        "proposal",
    }
)
CONTACTED_PIPELINE_STATUSES = frozenset(
    {
        "contacted",
        "replied",
        "meeting",
        "proposal",
    }
)
PRIORITY_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


class FollowUpPermissionError(PermissionError):
    """Raised when the actor is not an active CRM user."""


class FollowUpFilterError(ValueError):
    """Raised when a command-center filter is malformed."""


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


def _positive_id(
    value: Any,
    field_name: str,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FollowUpFilterError(
            f"{field_name} must be a positive integer."
        )
    return value


def _optional_filter_id(
    value: int | None,
    field_name: str,
) -> int | None:
    if value is None:
        return None
    return _positive_id(value, field_name)


def _load_active_actor(
    db: sqlite3.Connection,
    actor: Record | None,
) -> dict[str, Any]:
    try:
        actor_id = _positive_id(
            _value(actor, "id"),
            "Actor ID",
        )
    except FollowUpFilterError as exc:
        raise FollowUpPermissionError(
            "An authenticated CRM user is required."
        ) from exc

    row = db.execute(
        """
        SELECT
            id,
            username,
            display_name,
            role,
            active
        FROM users
        WHERE id = ?
          AND active = 1
        """,
        (actor_id,),
    ).fetchone()
    if row is None or row["role"] not in CRM_ROLES:
        raise FollowUpPermissionError(
            "An active CRM role is required."
        )
    return dict(row)


def resolve_manila_today(
    now_utc: datetime | None = None,
) -> date:
    """Resolve the operational date using Asia/Manila boundaries."""
    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError(
            "The current time must include timezone information."
        )
    return current.astimezone(MANILA_TIMEZONE).date()


def _operational_today(
    today: date | None,
    now_utc: datetime | None,
) -> date:
    if today is None:
        return resolve_manila_today(now_utc)
    if isinstance(today, datetime) or not isinstance(today, date):
        raise ValueError("Today must be a date.")
    if now_utc is not None:
        raise ValueError(
            "Provide either today or now_utc, not both."
        )
    return today


def _parse_date(
    value: Any,
) -> date | None:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    try:
        return date.fromisoformat(clean)
    except ValueError:
        return None


def _parse_stored_datetime(
    value: Any,
) -> datetime | None:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    parse_value = (
        clean[:-1] + "+00:00"
        if clean.endswith(("Z", "z"))
        else clean
    )
    try:
        parsed = datetime.fromisoformat(parse_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MANILA_TIMEZONE)


def _activity_states(
    db: sqlite3.Connection,
    lead_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if not lead_ids:
        return {}

    placeholders = ", ".join("?" for _ in lead_ids)
    rows = db.execute(
        f"""
        SELECT
            id,
            lead_id,
            activity_type,
            activity_at,
            channel,
            response_status,
            next_follow_up_date
        FROM lead_activities
        WHERE deleted_at IS NULL
          AND lead_id IN ({placeholders})
        ORDER BY
            activity_at DESC,
            id DESC
        """,
        lead_ids,
    ).fetchall()

    states: dict[int, dict[str, Any]] = {
        lead_id: {
            "last_activity_at": None,
            "activity_follow_up_date": None,
            "last_contact_at": None,
            "last_contact_channel": None,
            "last_response_status": None,
        }
        for lead_id in lead_ids
    }

    for row in rows:
        lead_id = int(row["lead_id"])
        state = states[lead_id]

        if state["last_activity_at"] is None:
            state["last_activity_at"] = row["activity_at"]

        if (
            state["activity_follow_up_date"] is None
            and row["next_follow_up_date"] is not None
        ):
            state["activity_follow_up_date"] = (
                row["next_follow_up_date"]
            )

        if (
            state["last_contact_at"] is None
            and str(row["channel"]).strip().casefold()
            != "internal"
        ):
            state["last_contact_at"] = row["activity_at"]
            state["last_contact_channel"] = row["channel"]
            state["last_response_status"] = row[
                "response_status"
            ]

    return states


def _filter_options(
    leads: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    definitions = {
        "assignees": (
            "assigned_to_user_id",
            "assigned_to_name",
            "assigned_to_username",
        ),
        "researchers": (
            "researched_by_user_id",
            "researched_by_name",
            "researched_by_username",
        ),
        "business_development_owners": (
            "business_development_owner_user_id",
            "business_development_owner_name",
            "business_development_owner_username",
        ),
    }
    result: dict[str, list[dict[str, Any]]] = {}

    for option_key, (
        id_field,
        name_field,
        username_field,
    ) in definitions.items():
        options: dict[int, dict[str, Any]] = {}
        for lead in leads:
            value = lead.get(id_field)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                continue
            display_name = (
                str(lead.get(name_field) or "").strip()
                or str(lead.get(username_field) or "").strip()
                or f"User {value}"
            )
            options[value] = {
                "id": value,
                "display_name": display_name,
            }
        result[option_key] = sorted(
            options.values(),
            key=lambda item: (
                str(item["display_name"]).casefold(),
                int(item["id"]),
            ),
        )

    return result


def _matches_filters(
    lead: dict[str, Any],
    *,
    assignee_id: int | None,
    researcher_id: int | None,
    business_development_owner_id: int | None,
) -> bool:
    if (
        assignee_id is not None
        and lead.get("assigned_to_user_id") != assignee_id
    ):
        return False
    if (
        researcher_id is not None
        and lead.get("researched_by_user_id")
        != researcher_id
    ):
        return False
    if (
        business_development_owner_id is not None
        and lead.get(
            "business_development_owner_user_id"
        )
        != business_development_owner_id
    ):
        return False
    return True


def _enrich_lead(
    lead: dict[str, Any],
    activity_state: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(lead)
    activity_due = _parse_date(
        activity_state["activity_follow_up_date"]
    )
    lead_due = _parse_date(
        lead.get("next_action_due_date")
    )
    effective_due = activity_due or lead_due

    contact_datetime = _parse_stored_datetime(
        activity_state["last_contact_at"]
    )

    enriched.update(
        {
            "last_activity_at": activity_state[
                "last_activity_at"
            ],
            "activity_follow_up_date": (
                activity_due.isoformat()
                if activity_due is not None
                else None
            ),
            "effective_due_date": (
                effective_due.isoformat()
                if effective_due is not None
                else None
            ),
            "due_source": (
                "activity"
                if activity_due is not None
                else "lead"
                if lead_due is not None
                else None
            ),
            "last_contact_at": activity_state[
                "last_contact_at"
            ],
            "last_contact_date": (
                contact_datetime.date().isoformat()
                if contact_datetime is not None
                else None
            ),
            "last_contact_channel": activity_state[
                "last_contact_channel"
            ],
            "last_response_status": activity_state[
                "last_response_status"
            ],
            "action_url": f"/crm/leads/{lead['id']}",
            "_effective_due_date": effective_due,
            "_last_contact_datetime": contact_datetime,
            "_last_contact_date": (
                contact_datetime.date()
                if contact_datetime is not None
                else None
            ),
            "_submitted_at": _parse_stored_datetime(
                lead.get("submitted_for_review_at")
            ),
            "_reviewed_at": _parse_stored_datetime(
                lead.get("reviewed_at")
            ),
            "_outreach_approved_at": (
                _parse_stored_datetime(
                    lead.get("outreach_approved_at")
                )
            ),
        }
    )
    return enriched


def _priority_rank(
    lead: dict[str, Any],
) -> int:
    return PRIORITY_ORDER.get(
        str(lead.get("priority") or "").casefold(),
        3,
    )


def _due_sort(
    lead: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        lead["_effective_due_date"] or date.max,
        _priority_rank(lead),
        int(lead["id"]),
    )


def _proposal_sort(
    lead: dict[str, Any],
) -> tuple[Any, ...]:
    due = lead["_effective_due_date"]
    return (
        0 if due is None else 1,
        due or date.min,
        _priority_rank(lead),
        int(lead["id"]),
    )


def _contact_sort(
    lead: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        lead["_last_contact_datetime"]
        or datetime.min.replace(
            tzinfo=MANILA_TIMEZONE
        ),
        _priority_rank(lead),
        int(lead["id"]),
    )


def _stale_sort(
    lead: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        lead["_last_contact_date"] or date.min,
        _priority_rank(lead),
        int(lead["id"]),
    )


def _workflow_sort(
    date_field: str,
) -> Callable[[dict[str, Any]], tuple[Any, ...]]:
    def sort_key(
        lead: dict[str, Any],
    ) -> tuple[Any, ...]:
        return (
            lead[date_field]
            or datetime.min.replace(
                tzinfo=MANILA_TIMEZONE
            ),
            _priority_rank(lead),
            int(lead["id"]),
        )

    return sort_key


def _public_lead(
    lead: dict[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in lead.items()
        if not key.startswith("_")
    }


def _queue(
    *,
    key: str,
    title: str,
    description: str,
    empty_message: str,
    leads: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
    sort_key: Callable[
        [dict[str, Any]],
        tuple[Any, ...],
    ],
) -> dict[str, Any]:
    items = sorted(
        (
            lead
            for lead in leads
            if predicate(lead)
        ),
        key=sort_key,
    )
    return {
        "key": key,
        "title": title,
        "description": description,
        "empty_message": empty_message,
        "count": len(items),
        "leads": [
            _public_lead(lead)
            for lead in items
        ],
    }


def build_follow_up_command_center(
    db: sqlite3.Connection,
    actor: Record | None,
    *,
    today: date | None = None,
    now_utc: datetime | None = None,
    assignee_id: int | None = None,
    researcher_id: int | None = None,
    business_development_owner_id: int | None = None,
) -> dict[str, Any]:
    """Build all Phase 6.4 queues for one database-verified CRM actor."""
    database_actor = _load_active_actor(
        db,
        actor,
    )
    operational_date = _operational_today(
        today,
        now_utc,
    )
    week_end = operational_date + timedelta(
        days=6 - operational_date.weekday()
    )
    stale_cutoff = operational_date - timedelta(
        days=5
    )

    safe_assignee_id = _optional_filter_id(
        assignee_id,
        "Assignee filter",
    )
    safe_researcher_id = _optional_filter_id(
        researcher_id,
        "Researcher filter",
    )
    safe_business_owner_id = _optional_filter_id(
        business_development_owner_id,
        "Business Development Owner filter",
    )

    visible_leads = [
        dict(row)
        for row in list_visible_leads(
            db,
            database_actor,
        )
    ]
    options = _filter_options(visible_leads)
    filtered_leads = [
        lead
        for lead in visible_leads
        if _matches_filters(
            lead,
            assignee_id=safe_assignee_id,
            researcher_id=safe_researcher_id,
            business_development_owner_id=(
                safe_business_owner_id
            ),
        )
    ]

    activity_states = _activity_states(
        db,
        [
            int(lead["id"])
            for lead in filtered_leads
        ],
    )
    enriched = [
        _enrich_lead(
            lead,
            activity_states.get(
                int(lead["id"]),
                {
                    "last_activity_at": None,
                    "activity_follow_up_date": None,
                    "last_contact_at": None,
                    "last_contact_channel": None,
                    "last_response_status": None,
                },
            ),
        )
        for lead in filtered_leads
    ]

    def active(
        lead: dict[str, Any],
    ) -> bool:
        return (
            str(
                lead.get("pipeline_status")
                or ""
            ).casefold()
            in ACTIVE_PIPELINE_STATUSES
        )

    queues = [
        _queue(
            key="due_today",
            title="Due Today",
            description=(
                "Follow-up or next-action work due on the "
                "current Manila date."
            ),
            empty_message="Nothing is due today.",
            leads=enriched,
            predicate=lambda lead: (
                active(lead)
                and lead["_effective_due_date"]
                == operational_date
            ),
            sort_key=_due_sort,
        ),
        _queue(
            key="overdue",
            title="Overdue",
            description=(
                "Follow-up or next-action work before the "
                "current Manila date."
            ),
            empty_message="No follow-up work is overdue.",
            leads=enriched,
            predicate=lambda lead: (
                active(lead)
                and lead["_effective_due_date"]
                is not None
                and lead["_effective_due_date"]
                < operational_date
            ),
            sort_key=_due_sort,
        ),
        _queue(
            key="due_this_week",
            title="Due This Week",
            description=(
                "Work due after today through Sunday in "
                "Asia/Manila."
            ),
            empty_message="Nothing else is due this week.",
            leads=enriched,
            predicate=lambda lead: (
                active(lead)
                and lead["_effective_due_date"]
                is not None
                and operational_date
                < lead["_effective_due_date"]
                <= week_end
            ),
            sort_key=_due_sort,
        ),
        _queue(
            key="waiting_for_reply",
            title="Waiting for Reply",
            description=(
                "The latest external activity is awaiting "
                "a prospect response."
            ),
            empty_message="No visible leads are waiting for a reply.",
            leads=enriched,
            predicate=lambda lead: (
                active(lead)
                and lead.get("last_response_status")
                == "awaiting_reply"
            ),
            sort_key=_contact_sort,
        ),
        _queue(
            key="no_contact_five_days",
            title="No Contact for Five Days",
            description=(
                "Contacted-or-later leads with no external "
                "activity in the last five Manila dates."
            ),
            empty_message="No contacted leads are stale.",
            leads=enriched,
            predicate=lambda lead: (
                str(
                    lead.get("pipeline_status")
                    or ""
                ).casefold()
                in CONTACTED_PIPELINE_STATUSES
                and (
                    lead["_last_contact_date"] is None
                    or lead["_last_contact_date"]
                    <= stale_cutoff
                )
            ),
            sort_key=_stale_sort,
        ),
        _queue(
            key="approved_not_contacted",
            title="Approved but Not Contacted",
            description=(
                "Research and outreach are approved, but "
                "the first audited contact is still missing."
            ),
            empty_message=(
                "No approved leads are waiting for first contact."
            ),
            leads=enriched,
            predicate=lambda lead: (
                lead.get("research_status")
                == "approved"
                and lead.get(
                    "outreach_approved_by_user_id"
                )
                is not None
                and lead.get("outreach_approved_at")
                is not None
                and lead.get("pipeline_status")
                in {"new", "reviewed"}
            ),
            sort_key=_workflow_sort(
                "_outreach_approved_at"
            ),
        ),
        _queue(
            key="research_awaiting_review",
            title="Research Awaiting Review",
            description=(
                "Submitted research that needs the Owner's "
                "decision."
            ),
            empty_message="No research is awaiting review.",
            leads=enriched,
            predicate=lambda lead: (
                lead.get("research_status")
                == "ready_for_review"
            ),
            sort_key=_workflow_sort("_submitted_at"),
        ),
        _queue(
            key="changes_requested",
            title="Changes Requested",
            description=(
                "Research returned for correction and "
                "resubmission."
            ),
            empty_message="No research changes are outstanding.",
            leads=enriched,
            predicate=lambda lead: (
                lead.get("research_status")
                == "changes_requested"
            ),
            sort_key=_workflow_sort("_reviewed_at"),
        ),
        _queue(
            key="interested_handoff",
            title="Interested — Handoff to Mark",
            description=(
                "The latest external response is interested "
                "and needs Owner attention."
            ),
            empty_message="No interested replies need handoff.",
            leads=enriched,
            predicate=lambda lead: (
                active(lead)
                and lead.get("last_response_status")
                == "interested"
            ),
            sort_key=_contact_sort,
        ),
        _queue(
            key="proposal_follow_up",
            title="Proposal Follow-up Required",
            description=(
                "Proposal-stage leads with no follow-up date "
                "or a follow-up due today or earlier."
            ),
            empty_message=(
                "No proposal follow-up currently requires action."
            ),
            leads=enriched,
            predicate=lambda lead: (
                lead.get("pipeline_status")
                == "proposal"
                and (
                    lead["_effective_due_date"] is None
                    or lead["_effective_due_date"]
                    <= operational_date
                )
            ),
            sort_key=_proposal_sort,
        ),
    ]

    return {
        "actor_role": database_actor["role"],
        "operational_date": operational_date.isoformat(),
        "week_ends_on": week_end.isoformat(),
        "timezone": "Asia/Manila",
        "visible_lead_count": len(visible_leads),
        "filtered_lead_count": len(filtered_leads),
        "selected_filters": {
            "assignee_id": safe_assignee_id,
            "researcher_id": safe_researcher_id,
            "business_development_owner_id": (
                safe_business_owner_id
            ),
        },
        "filter_options": options,
        "queues": queues,
        "queue_by_key": {
            queue["key"]: queue
            for queue in queues
        },
    }
