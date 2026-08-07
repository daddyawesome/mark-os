from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import date
from typing import Any

from app.db.organizations import organization_id_by_slug
from app.services.access_control import (
    has_crm_owner_authority,
    is_owner,
    is_relationship_manager,
)
from app.services.lead_research_permissions import LeadPermissionError
from app.services.leads import get_lead, require_lead_version, update_lead_next_action
from app.services.workspace_context import load_crm_actor_for_workspace
from app.services.playbooks import (
    get_primary_playbook_for_user,
    render_markdown_safely,
)


Record = Mapping[str, Any] | sqlite3.Row


def _value(record: Record | None, key: str, default: Any = None) -> Any:
    if record is None:
        return default
    try:
        return record[key]
    except (KeyError, IndexError, TypeError):
        return default


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _actor_id(actor: Record | None) -> int:
    value = _value(actor, "id")
    return _positive_id(value, "Actor ID")


def _organization_id(
    db: sqlite3.Connection,
    organization_id: int | None,
) -> int:
    if organization_id is None:
        return organization_id_by_slug(db, "mark-agency")
    return _positive_id(organization_id, "Organization ID")


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


def relationship_manager_matches_lead(
    actor: Record | None,
    lead: Record | None,
) -> bool:
    if not is_relationship_manager(actor) or lead is None:
        return False
    if has_crm_owner_authority(actor):
        return True
    actor_id = _actor_id(actor)
    return actor_id in {
        _value(lead, "business_development_owner_user_id"),
        _value(lead, "created_by_user_id"),
    }


def can_update_relationship_next_action(
    actor: Record | None,
    lead: Record | None,
) -> bool:
    if lead is None or _value(lead, "deleted_at") is not None:
        return False
    return has_crm_owner_authority(actor) or relationship_manager_matches_lead(actor, lead)


def update_next_action_for_actor(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    next_action: str,
    next_action_due_date: str | None = None,
    organization_id: int | None = None,
    expected_row_version: int | None = None,
) -> sqlite3.Row:
    safe_organization_id = _organization_id(db, organization_id)
    actor = _actor_for_workspace(db, actor, organization_id)
    lead = get_lead(
        db,
        _positive_id(lead_id, "Lead ID"),
        organization_id=safe_organization_id,
    )
    if not can_update_relationship_next_action(actor, lead):
        raise LeadPermissionError(
            "You are not allowed to update this lead's next action."
        )
    return update_lead_next_action(
        db,
        lead_id,
        next_action=next_action,
        next_action_due_date=next_action_due_date,
        organization_id=safe_organization_id,
        expected_row_version=expected_row_version,
    )


def list_active_relationship_managers(
    db: sqlite3.Connection,
    *,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    safe_organization_id = _organization_id(db, organization_id)
    rows = db.execute(
        """
        SELECT id, username, display_name
        FROM users
        JOIN organization_memberships AS membership
          ON membership.user_id = users.id
         AND membership.organization_id = ?
        WHERE role = 'relationship_manager'
          AND users.active = 1
          AND membership.active = 1
        ORDER BY display_name COLLATE NOCASE, id
        """,
        (safe_organization_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def assign_relationship_manager(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    actor: Record,
    relationship_manager_user_id: int | None,
    organization_id: int | None = None,
    expected_row_version: int | None = None,
) -> sqlite3.Row:
    safe_lead_id = _positive_id(lead_id, "Lead ID")
    safe_organization_id = _organization_id(db, organization_id)
    actor = _actor_for_workspace(db, actor, organization_id)
    if not has_crm_owner_authority(actor):
        raise LeadPermissionError(
            "Workspace owner authority is required to assign a Relationship Manager."
        )
    lead = get_lead(
        db,
        safe_lead_id,
        organization_id=safe_organization_id,
    )
    if lead is None:
        raise ValueError("Lead not found.")
    safe_expected = require_lead_version(lead, expected_row_version)

    manager_id = None
    manager_name = "Unassigned"
    if relationship_manager_user_id is not None:
        manager_id = _positive_id(
            relationship_manager_user_id,
            "Relationship Manager user ID",
        )
        manager = db.execute(
            """
            SELECT id, display_name
            FROM users
            JOIN organization_memberships AS membership
              ON membership.user_id = users.id
             AND membership.organization_id = ?
            WHERE users.id = ?
              AND users.role = 'relationship_manager'
              AND users.active = 1
              AND membership.active = 1
            """,
            (safe_organization_id, manager_id),
        ).fetchone()
        if manager is None:
            raise ValueError(
                "Relationship Manager must reference an active account."
            )
        manager_name = str(manager["display_name"])

    if lead["business_development_owner_user_id"] == manager_id:
        return lead

    cursor = db.execute(
        """
        UPDATE leads
        SET business_development_owner_user_id = ?,
            row_version = row_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND organization_id = ?
          AND deleted_at IS NULL
          AND (? IS NULL OR row_version = ?)
        """,
        (
            manager_id,
            safe_lead_id,
            safe_organization_id,
            safe_expected,
            safe_expected,
        ),
    )
    if cursor.rowcount != 1:
        reloaded = get_lead(
            db,
            safe_lead_id,
            organization_id=safe_organization_id,
        )
        if reloaded is not None:
            require_lead_version(reloaded, safe_expected)
        raise ValueError("Lead not found.")

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
            'crm_relationship_owner'
        FROM tasks
        WHERE id = ?
        """,
        (
            f"Business development owner set to {manager_name}.",
            lead["quest_id"],
        ),
    )

    updated = get_lead(
        db,
        safe_lead_id,
        organization_id=safe_organization_id,
    )
    if updated is None:
        raise RuntimeError("Assigned lead could not be reloaded.")
    return updated


def _relationship_lead_select() -> str:
    return """
        SELECT
            l.*,
            creator.display_name AS created_by_name,
            assignee.display_name AS assigned_to_name,
            researcher.display_name AS researched_by_name,
            manager.display_name AS business_development_owner_name
        FROM leads AS l
        LEFT JOIN users AS creator
          ON creator.id = l.created_by_user_id
        LEFT JOIN users AS assignee
          ON assignee.id = l.assigned_to_user_id
        LEFT JOIN users AS researcher
          ON researcher.id = l.researched_by_user_id
        LEFT JOIN users AS manager
          ON manager.id = l.business_development_owner_user_id
    """


def _relationship_visibility_sql(*, workspace_owner: bool) -> str:
    if workspace_owner:
        return """
            l.organization_id = ?
            AND l.deleted_at IS NULL
        """
    return """
        l.organization_id = ?
        AND l.deleted_at IS NULL
        AND (
            l.business_development_owner_user_id = ?
            OR l.created_by_user_id = ?
        )
    """


def _lead_rows(
    db: sqlite3.Connection,
    user_id: int,
    extra_condition: str,
    *,
    organization_id: int,
    limit: int = 8,
    workspace_owner: bool = False,
) -> list[dict[str, Any]]:
    visibility_sql = _relationship_visibility_sql(workspace_owner=workspace_owner)
    parameters = (
        (organization_id, limit)
        if workspace_owner
        else (organization_id, user_id, user_id, limit)
    )
    rows = db.execute(
        f"""
        {_relationship_lead_select()}
        WHERE {visibility_sql}
          AND ({extra_condition})
        ORDER BY
            CASE l.priority
                WHEN 'high' THEN 0
                WHEN 'medium' THEN 1
                ELSE 2
            END,
            COALESCE(l.next_action_due_date, '9999-12-31'),
            l.updated_at DESC,
            l.id DESC
        LIMIT ?
        """,
        parameters,
    ).fetchall()
    return [dict(row) for row in rows]


def _count(
    db: sqlite3.Connection,
    user_id: int,
    extra_condition: str,
    *,
    organization_id: int,
    workspace_owner: bool = False,
) -> int:
    visibility_sql = _relationship_visibility_sql(workspace_owner=workspace_owner)
    parameters = (
        (organization_id,)
        if workspace_owner
        else (organization_id, user_id, user_id)
    )
    return int(
        db.execute(
            f"""
            SELECT COUNT(*) AS item_count
            FROM leads AS l
            WHERE {visibility_sql}
              AND ({extra_condition})
            """,
            parameters,
        ).fetchone()["item_count"]
    )


def load_relationship_manager_dashboard(
    db: sqlite3.Connection,
    actor: Record,
    *,
    organization_id: int | None = None,
) -> dict[str, Any]:
    if not is_relationship_manager(actor):
        raise LeadPermissionError(
            "Relationship Manager access is required."
        )

    safe_organization_id = _organization_id(db, organization_id)
    actor = _actor_for_workspace(db, actor, organization_id)
    user_id = _actor_id(actor)
    workspace_owner = has_crm_owner_authority(actor)
    today = date.today().isoformat()
    playbook = get_primary_playbook_for_user(db, user_id)
    if playbook is not None:
        playbook["rendered_content"] = render_markdown_safely(
            playbook["markdown_content"]
        )

    qualification_condition = """
        l.pipeline_status IN ('new', 'reviewed')
        AND l.research_status IN (
            'draft',
            'researching',
            'changes_requested'
        )
    """
    ready_condition = """
        l.research_status = 'approved'
        AND l.outreach_approved_by_user_id IS NOT NULL
        AND l.outreach_approved_at IS NOT NULL
        AND l.pipeline_status IN ('new', 'reviewed')
    """
    due_condition = f"""
        l.next_action_due_date IS NOT NULL
        AND l.next_action_due_date <= '{today}'
        AND l.pipeline_status NOT IN ('won', 'lost')
    """
    waiting_condition = """
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
    """
    handoff_condition = """
        l.pipeline_status IN ('replied', 'meeting')
    """

    metric_cards = [
        {
            "label": "Relationship leads",
            "value": _count(db, user_id, "1 = 1", organization_id=safe_organization_id, workspace_owner=workspace_owner),
        },
        {
            "label": "Approved outreach",
            "value": _count(db, user_id, ready_condition, organization_id=safe_organization_id, workspace_owner=workspace_owner),
        },
        {
            "label": "Follow-ups due",
            "value": _count(db, user_id, due_condition, organization_id=safe_organization_id, workspace_owner=workspace_owner),
        },
        {
            "label": "Replies / meetings",
            "value": _count(db, user_id, handoff_condition, organization_id=safe_organization_id, workspace_owner=workspace_owner),
        },
    ]

    queues = [
        {
            "key": "qualification",
            "title": "Qualify and coordinate",
            "description": (
                "New relationship leads that need a clear next action "
                "while research evidence is being completed."
            ),
            "leads": _lead_rows(db, user_id, qualification_condition, organization_id=safe_organization_id, workspace_owner=workspace_owner),
        },
        {
            "key": "ready_outreach",
            "title": "Approved outreach",
            "description": (
                "Research and Owner outreach approval are complete. "
                "Contact logging remains locked until Phase 6.2."
            ),
            "leads": _lead_rows(db, user_id, ready_condition, organization_id=safe_organization_id, workspace_owner=workspace_owner),
        },
        {
            "key": "followups_due",
            "title": "Follow-ups due",
            "description": (
                "Relationship leads whose next action is due today or overdue."
            ),
            "leads": _lead_rows(db, user_id, due_condition, organization_id=safe_organization_id, workspace_owner=workspace_owner),
        },
        {
            "key": "waiting_mark",
            "title": "Waiting for Mark",
            "description": (
                "Research review or outreach approval still needs the Owner."
            ),
            "leads": _lead_rows(db, user_id, waiting_condition, organization_id=safe_organization_id, workspace_owner=workspace_owner),
        },
        {
            "key": "handoff",
            "title": "Handoff to Mark",
            "description": (
                "Interested prospects at Reply or Meeting stage."
            ),
            "leads": _lead_rows(db, user_id, handoff_condition, organization_id=safe_organization_id, workspace_owner=workspace_owner),
        },
    ]

    return {
        "playbook": playbook,
        "metric_cards": metric_cards,
        "queues": queues,
    }
