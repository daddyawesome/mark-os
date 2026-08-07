from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from app.db.organizations import organization_id_by_slug
from app.services.workspace_context import require_workspace_membership
from app.services.access_control import (
    is_lead_sourcer,
    is_owner,
    is_relationship_manager,
)


Record = Mapping[str, Any] | sqlite3.Row
QUEUE_PREVIEW_LIMIT = 6

_LEAD_SELECT = """
SELECT
    l.*,
    creator.display_name AS created_by_name,
    creator.username AS created_by_username,
    assignee.display_name AS assigned_to_name,
    assignee.username AS assigned_to_username,
    researcher.display_name AS researched_by_name,
    researcher.username AS researched_by_username,
    relationship_manager.display_name AS business_development_owner_name,
    relationship_manager.username AS business_development_owner_username
FROM leads AS l
LEFT JOIN users AS creator
    ON creator.id = l.created_by_user_id
LEFT JOIN users AS assignee
    ON assignee.id = l.assigned_to_user_id
LEFT JOIN users AS researcher
    ON researcher.id = l.researched_by_user_id
LEFT JOIN users AS relationship_manager
    ON relationship_manager.id = l.business_development_owner_user_id
"""

_DEFAULT_ORDER = """
CASE l.priority
    WHEN 'high' THEN 0
    WHEN 'medium' THEN 1
    ELSE 2
END,
COALESCE(l.next_action_due_date, '9999-12-31'),
l.updated_at DESC,
l.id DESC
"""


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


def _positive_user_id(user: Record | None) -> int | None:
    value = _value(user, "id")
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        return None
    return value


def _visibility_clause(
    db: sqlite3.Connection,
    user: Record | None,
    organization_id: int | None = None,
) -> tuple[str, list[object]]:
    safe_organization_id = (
        organization_id_by_slug(db, "mark-agency")
        if organization_id is None
        else int(organization_id)
    )
    if safe_organization_id <= 0:
        raise ValueError("Organization ID must be a positive integer.")

    if organization_id is not None:
        user_id = _positive_user_id(user)
        if user_id is None:
            raise PermissionError("CRM workspace membership is required.")
        require_workspace_membership(
            db,
            user_id,
            safe_organization_id,
        )

    organization_sql = "l.organization_id = ?"

    if is_owner(user):
        return organization_sql, [safe_organization_id]

    if is_lead_sourcer(user):
        user_id = _positive_user_id(user)
        if user_id is None:
            return "0 = 1", []
        return (
            f"""
            {organization_sql}
            AND (
                l.created_by_user_id = ?
                OR l.assigned_to_user_id = ?
                OR l.researched_by_user_id = ?
            )
            """,
            [safe_organization_id, user_id, user_id, user_id],
        )

    if is_relationship_manager(user):
        user_id = _positive_user_id(user)
        if user_id is None:
            return "0 = 1", []
        return (
            f"""
            {organization_sql}
            AND (
                l.business_development_owner_user_id = ?
                OR l.created_by_user_id = ?
            )
            """,
            [safe_organization_id, user_id, user_id],
        )

    return "0 = 1", []


def _queue_rows(
    db: sqlite3.Connection,
    *,
    visibility_sql: str,
    visibility_parameters: list[object],
    queue_sql: str,
    queue_parameters: list[object] | None = None,
    order_by: str = _DEFAULT_ORDER,
    limit: int = QUEUE_PREVIEW_LIMIT,
) -> list[dict[str, Any]]:
    parameters = [
        *visibility_parameters,
        *(queue_parameters or []),
        limit,
    ]
    rows = db.execute(
        f"""
        {_LEAD_SELECT}
        WHERE l.deleted_at IS NULL
          AND ({visibility_sql})
          AND ({queue_sql})
        ORDER BY {order_by}
        LIMIT ?
        """,
        parameters,
    ).fetchall()
    return [dict(row) for row in rows]


def _queue_count(
    db: sqlite3.Connection,
    *,
    visibility_sql: str,
    visibility_parameters: list[object],
    queue_sql: str,
    queue_parameters: list[object] | None = None,
) -> int:
    row = db.execute(
        f"""
        SELECT COUNT(*) AS queue_count
        FROM leads AS l
        WHERE l.deleted_at IS NULL
          AND ({visibility_sql})
          AND ({queue_sql})
        """,
        [
            *visibility_parameters,
            *(queue_parameters or []),
        ],
    ).fetchone()
    return int(row["queue_count"] or 0)


def _queue_card(
    db: sqlite3.Connection,
    *,
    visibility_sql: str,
    visibility_parameters: list[object],
    key: str,
    title: str,
    description: str,
    empty_message: str,
    action_label: str,
    queue_sql: str,
    action_path: str,
    order_by: str = _DEFAULT_ORDER,
) -> dict[str, Any]:
    leads = _queue_rows(
        db,
        visibility_sql=visibility_sql,
        visibility_parameters=visibility_parameters,
        queue_sql=queue_sql,
        order_by=order_by,
    )
    for lead in leads:
        lead["queue_action_url"] = action_path.format(
            lead_id=lead["id"],
        )

    return {
        "key": key,
        "title": title,
        "description": description,
        "empty_message": empty_message,
        "action_label": action_label,
        "count": _queue_count(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            queue_sql=queue_sql,
        ),
        "leads": leads,
    }


def list_visible_leads(
    db: sqlite3.Connection,
    user: Record | None,
    *,
    organization_id: int | None = None,
) -> list[sqlite3.Row]:
    """Return active leads visible to the actor inside one workspace."""
    visibility_sql, parameters = _visibility_clause(
        db,
        user,
        organization_id,
    )
    return db.execute(
        f"""
        {_LEAD_SELECT}
        WHERE l.deleted_at IS NULL
          AND ({visibility_sql})
        ORDER BY
            CASE l.priority
                WHEN 'high' THEN 0
                WHEN 'medium' THEN 1
                ELSE 2
            END,
            CASE l.research_status
                WHEN 'changes_requested' THEN 0
                WHEN 'ready_for_review' THEN 1
                WHEN 'researching' THEN 2
                WHEN 'draft' THEN 3
                WHEN 'approved' THEN 4
                ELSE 5
            END,
            CASE l.pipeline_status
                WHEN 'proposal' THEN 0
                WHEN 'meeting' THEN 1
                WHEN 'replied' THEN 2
                WHEN 'contacted' THEN 3
                WHEN 'reviewed' THEN 4
                WHEN 'new' THEN 5
                WHEN 'won' THEN 6
                ELSE 7
            END,
            COALESCE(
                l.next_action_due_date,
                '9999-12-31'
            ),
            l.updated_at DESC,
            l.id DESC
        """,
        parameters,
    ).fetchall()


def _owner_queues(
    db: sqlite3.Connection,
    *,
    visibility_sql: str,
    visibility_parameters: list[object],
) -> list[dict[str, Any]]:
    return [
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="owner_review",
            title="Research waiting for review",
            description=(
                "Submitted work that needs an Owner "
                "decision."
            ),
            empty_message=(
                "No research is waiting for review."
            ),
            action_label="Review research",
            queue_sql=(
                "l.research_status = "
                "'ready_for_review'"
            ),
            action_path="/crm/leads/{lead_id}",
            order_by="""
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
        ),
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="owner_outreach",
            title="Outreach approval required",
            description=(
                "Approved research that still needs "
                "permission before first contact."
            ),
            empty_message=(
                "No leads need outreach approval."
            ),
            action_label="Approve outreach",
            queue_sql="""
                l.research_status = 'approved'
                AND (
                    l.outreach_approved_by_user_id
                        IS NULL
                    OR l.outreach_approved_at IS NULL
                )
                AND l.pipeline_status
                    IN ('new', 'reviewed')
            """,
            action_path="/crm/leads/{lead_id}",
            order_by="""
                COALESCE(
                    l.reviewed_at,
                    l.updated_at
                ) ASC,
                CASE l.priority
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                l.id ASC
            """,
        ),
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="owner_ready_contact",
            title="Ready for first contact",
            description=(
                "Research and outreach approval are "
                "complete."
            ),
            empty_message=(
                "No approved leads are waiting for "
                "first contact."
            ),
            action_label="Open lead",
            queue_sql="""
                l.research_status = 'approved'
                AND l.outreach_approved_by_user_id
                    IS NOT NULL
                AND l.outreach_approved_at IS NOT NULL
                AND l.pipeline_status
                    IN ('new', 'reviewed')
            """,
            action_path="/crm/leads/{lead_id}",
            order_by="""
                COALESCE(
                    l.outreach_approved_at,
                    l.updated_at
                ) ASC,
                CASE l.priority
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                l.id ASC
            """,
        ),
    ]


def _researcher_queues(
    db: sqlite3.Connection,
    *,
    visibility_sql: str,
    visibility_parameters: list[object],
) -> list[dict[str, Any]]:
    return [
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="research_changes",
            title="Changes requested",
            description=(
                "Owner feedback that needs correction "
                "and resubmission."
            ),
            empty_message=(
                "No requested changes are waiting."
            ),
            action_label="Fix research",
            queue_sql=(
                "l.research_status = "
                "'changes_requested'"
            ),
            action_path=(
                "/crm/leads/{lead_id}/research/edit"
            ),
            order_by="""
                COALESCE(
                    l.reviewed_at,
                    l.updated_at
                ) ASC,
                CASE l.priority
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                l.id ASC
            """,
        ),
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="research_active",
            title="Research in progress",
            description=(
                "Draft and active research that can "
                "still be edited."
            ),
            empty_message=(
                "No active research is waiting."
            ),
            action_label="Continue research",
            queue_sql="""
                l.research_status
                    IN ('draft', 'researching')
            """,
            action_path=(
                "/crm/leads/{lead_id}/research/edit"
            ),
        ),
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="research_waiting",
            title="Waiting for Mark",
            description=(
                "Submitted research that is locked "
                "until the Owner decides."
            ),
            empty_message=(
                "No submissions are waiting for review."
            ),
            action_label="View submission",
            queue_sql=(
                "l.research_status = "
                "'ready_for_review'"
            ),
            action_path="/crm/leads/{lead_id}",
            order_by="""
                COALESCE(
                    l.submitted_for_review_at,
                    l.updated_at
                ) DESC,
                l.id DESC
            """,
        ),
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="research_decided",
            title="Owner decisions",
            description=(
                "Recently approved or rejected "
                "research."
            ),
            empty_message=(
                "No completed research decisions yet."
            ),
            action_label="View decision",
            queue_sql="""
                l.research_status
                    IN ('approved', 'rejected')
            """,
            action_path="/crm/leads/{lead_id}",
            order_by="""
                COALESCE(
                    l.reviewed_at,
                    l.updated_at
                ) DESC,
                l.id DESC
            """,
        ),
    ]


def _researcher_metric_cards(
    db: sqlite3.Connection,
    *,
    visibility_sql: str,
    visibility_parameters: list[object],
) -> list[dict[str, int | str]]:
    definitions = (
        (
            "Needs changes",
            "l.research_status = 'changes_requested'",
        ),
        (
            "In research",
            (
                "l.research_status "
                "IN ('draft', 'researching')"
            ),
        ),
        (
            "Waiting review",
            "l.research_status = 'ready_for_review'",
        ),
        (
            "Approved",
            "l.research_status = 'approved'",
        ),
    )
    return [
        {
            "label": label,
            "value": _queue_count(
                db,
                visibility_sql=visibility_sql,
                visibility_parameters=(
                    visibility_parameters
                ),
                queue_sql=queue_sql,
            ),
        }
        for label, queue_sql in definitions
    ]



def _relationship_manager_queues(
    db: sqlite3.Connection,
    *,
    visibility_sql: str,
    visibility_parameters: list[object],
) -> list[dict[str, Any]]:
    return [
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="relationship_qualification",
            title="Qualify and coordinate",
            description=(
                "New relationship leads that need a clear "
                "next action while research is completed."
            ),
            empty_message=(
                "No new relationship leads need qualification."
            ),
            action_label="Open lead",
            queue_sql="""
                l.pipeline_status IN ('new', 'reviewed')
                AND l.research_status IN (
                    'draft',
                    'researching',
                    'changes_requested'
                )
            """,
            action_path="/crm/leads/{lead_id}",
        ),
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="relationship_ready",
            title="Approved outreach",
            description=(
                "Research and Owner outreach approval "
                "are complete. Contact logging remains "
                "locked until Phase 6.2."
            ),
            empty_message=(
                "No assigned leads are ready for approved outreach."
            ),
            action_label="Open lead",
            queue_sql="""
                l.research_status = 'approved'
                AND l.outreach_approved_by_user_id IS NOT NULL
                AND l.outreach_approved_at IS NOT NULL
                AND l.pipeline_status IN ('new', 'reviewed')
            """,
            action_path="/crm/leads/{lead_id}",
        ),
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="relationship_due",
            title="Next actions due",
            description=(
                "Assigned relationship work due today or earlier."
            ),
            empty_message="No assigned next actions are overdue.",
            action_label="Update next action",
            queue_sql="""
                l.next_action_due_date IS NOT NULL
                AND l.next_action_due_date <= DATE('now')
                AND l.pipeline_status NOT IN ('won', 'lost')
            """,
            action_path="/crm/leads/{lead_id}",
        ),
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="relationship_waiting",
            title="Waiting for Mark",
            description=(
                "Research review or outreach approval still "
                "needs the Owner."
            ),
            empty_message="Nothing is waiting for Mark.",
            action_label="View status",
            queue_sql="""
                l.pipeline_status IN ('new', 'reviewed')
                AND (
                    l.research_status = 'ready_for_review'
                    OR (
                        l.research_status = 'approved'
                        AND (
                            l.outreach_approved_by_user_id IS NULL
                            OR l.outreach_approved_at IS NULL
                        )
                    )
                )
            """,
            action_path="/crm/leads/{lead_id}",
        ),
        _queue_card(
            db,
            visibility_sql=visibility_sql,
            visibility_parameters=visibility_parameters,
            key="relationship_handoff",
            title="Handoff to Mark",
            description=(
                "Interested prospects at Reply or Meeting stage."
            ),
            empty_message="No interested prospects need handoff.",
            action_label="Open handoff",
            queue_sql="""
                l.pipeline_status IN ('replied', 'meeting')
            """,
            action_path="/crm/leads/{lead_id}",
        ),
    ]


def _relationship_manager_metric_cards(
    db: sqlite3.Connection,
    *,
    visibility_sql: str,
    visibility_parameters: list[object],
) -> list[dict[str, int | str]]:
    definitions = (
        ("Relationship leads", "1 = 1"),
        (
            "Approved outreach",
            """
            l.research_status = 'approved'
            AND l.outreach_approved_by_user_id IS NOT NULL
            AND l.outreach_approved_at IS NOT NULL
            AND l.pipeline_status IN ('new', 'reviewed')
            """,
        ),
        (
            "Follow-ups due",
            """
            l.next_action_due_date IS NOT NULL
            AND l.next_action_due_date <= DATE('now')
            AND l.pipeline_status NOT IN ('won', 'lost')
            """,
        ),
        (
            "Replies / meetings",
            "l.pipeline_status IN ('replied', 'meeting')",
        ),
    )
    return [
        {
            "label": label,
            "value": _queue_count(
                db,
                visibility_sql=visibility_sql,
                visibility_parameters=visibility_parameters,
                queue_sql=queue_sql,
            ),
        }
        for label, queue_sql in definitions
    ]

def build_role_aware_crm_dashboard(
    db: sqlite3.Connection,
    user: Record | None,
    *,
    organization_id: int | None = None,
) -> dict[str, Any]:
    """Build deterministic CRM queues for the actor inside one workspace."""
    visibility_sql, parameters = _visibility_clause(
        db,
        user,
        organization_id,
    )
    leads = list_visible_leads(
        db,
        user,
        organization_id=organization_id,
    )

    if is_owner(user):
        return {
            "queue_mode": "owner",
            "queue_cards": _owner_queues(
                db,
                visibility_sql=visibility_sql,
                visibility_parameters=parameters,
            ),
            "metric_cards": None,
            "leads": leads,
        }

    if is_lead_sourcer(user):
        return {
            "queue_mode": "researcher",
            "queue_cards": _researcher_queues(
                db,
                visibility_sql=visibility_sql,
                visibility_parameters=parameters,
            ),
            "metric_cards": _researcher_metric_cards(
                db,
                visibility_sql=visibility_sql,
                visibility_parameters=parameters,
            ),
            "leads": leads,
        }

    if is_relationship_manager(user):
        return {
            "queue_mode": "relationship_manager",
            "queue_cards": _relationship_manager_queues(
                db,
                visibility_sql=visibility_sql,
                visibility_parameters=parameters,
            ),
            "metric_cards": _relationship_manager_metric_cards(
                db,
                visibility_sql=visibility_sql,
                visibility_parameters=parameters,
            ),
            "leads": leads,
        }

    return {
        "queue_mode": "none",
        "queue_cards": [],
        "metric_cards": [],
        "leads": [],
    }
