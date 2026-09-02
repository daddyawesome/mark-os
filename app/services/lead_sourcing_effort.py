from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.access_control import has_crm_owner_authority


Record = Mapping[str, Any] | sqlite3.Row


class EffortPermissionError(PermissionError):
    """Raised when an actor requests effort data they cannot view."""


@dataclass(frozen=True)
class LeadSourcingEffortSummary:
    user_id: int
    organization_id: int
    period_start: str
    period_end: str
    leads_researched: int
    leads_submitted: int
    changes_requested_count: int
    approved_count: int
    approval_rate: float | None
    relationship_actions: int
    research_minutes: None = None
    research_minutes_note: str = (
        "Not tracked. No research time-logging mechanism exists yet; this "
        "field is intentionally left unset rather than estimated."
    )


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required.")
    return value.strip()


def compute_lead_sourcing_effort(
    db: sqlite3.Connection,
    *,
    actor: Record,
    user_id: int,
    organization_id: int,
    period_start: str,
    period_end: str,
) -> LeadSourcingEffortSummary:
    """Derive effort metrics for one user from existing CRM records only.

    Every figure here is computed from data that already exists for other
    reasons (lead ownership, the research-review event log, logged
    activities) — nothing is a new, independently editable number, so this
    can never become payroll authority or be gamed by typing in a value.
    ``research_minutes`` has no backing data anywhere in MARK-OS today and is
    deliberately left unset rather than approximated or fabricated.
    """
    safe_user_id = _positive_id(user_id, "User ID")
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    safe_period_start = _required_text(period_start, "Period start")
    safe_period_end = _required_text(period_end, "Period end")

    is_self = bool(actor.get("id")) and int(actor["id"]) == safe_user_id
    if not is_self and not has_crm_owner_authority(actor):
        raise EffortPermissionError(
            "Only Mark, workspace-owner authority, or the user themselves "
            "may view this effort summary."
        )

    leads_researched = int(
        db.execute(
            """
            SELECT COUNT(DISTINCT id)
            FROM leads
            WHERE researched_by_user_id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
              AND updated_at BETWEEN ? AND ?
            """,
            (
                safe_user_id,
                safe_organization_id,
                safe_period_start,
                safe_period_end,
            ),
        ).fetchone()[0]
    )

    leads_submitted = int(
        db.execute(
            """
            SELECT COUNT(DISTINCT id)
            FROM leads
            WHERE researched_by_user_id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
              AND submitted_for_review_at IS NOT NULL
              AND submitted_for_review_at BETWEEN ? AND ?
            """,
            (
                safe_user_id,
                safe_organization_id,
                safe_period_start,
                safe_period_end,
            ),
        ).fetchone()[0]
    )

    changes_requested_count = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM quest_updates AS qu
            JOIN leads AS l ON l.quest_id = qu.task_id
            WHERE qu.event_type = 'crm_research_changes_requested'
              AND l.researched_by_user_id = ?
              AND l.organization_id = ?
              AND qu.created_at BETWEEN ? AND ?
            """,
            (
                safe_user_id,
                safe_organization_id,
                safe_period_start,
                safe_period_end,
            ),
        ).fetchone()[0]
    )

    approved_count = int(
        db.execute(
            """
            SELECT COUNT(DISTINCT l.id)
            FROM quest_updates AS qu
            JOIN leads AS l ON l.quest_id = qu.task_id
            WHERE qu.event_type = 'crm_research_approved'
              AND l.researched_by_user_id = ?
              AND l.organization_id = ?
              AND qu.created_at BETWEEN ? AND ?
            """,
            (
                safe_user_id,
                safe_organization_id,
                safe_period_start,
                safe_period_end,
            ),
        ).fetchone()[0]
    )

    approval_rate = (
        approved_count / leads_submitted if leads_submitted > 0 else None
    )

    relationship_actions = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM lead_activities AS la
            JOIN leads AS l ON l.id = la.lead_id
            WHERE la.performed_by_user_id = ?
              AND l.organization_id = ?
              AND la.deleted_at IS NULL
              AND la.activity_at BETWEEN ? AND ?
            """,
            (
                safe_user_id,
                safe_organization_id,
                safe_period_start,
                safe_period_end,
            ),
        ).fetchone()[0]
    )

    return LeadSourcingEffortSummary(
        user_id=safe_user_id,
        organization_id=safe_organization_id,
        period_start=safe_period_start,
        period_end=safe_period_end,
        leads_researched=leads_researched,
        leads_submitted=leads_submitted,
        changes_requested_count=changes_requested_count,
        approved_count=approved_count,
        approval_rate=approval_rate,
        relationship_actions=relationship_actions,
    )


def list_staff_for_effort_report(
    db: sqlite3.Connection,
    *,
    organization_id: int,
) -> list[dict[str, Any]]:
    """List active Lead Sourcers and Relationship Managers in one workspace."""
    rows = db.execute(
        """
        SELECT users.id, users.username, users.display_name, users.role
        FROM users
        JOIN organization_memberships AS membership
          ON membership.user_id = users.id
         AND membership.organization_id = ?
        WHERE users.role IN ('lead_sourcer', 'relationship_manager')
          AND users.active = 1
          AND membership.active = 1
        ORDER BY users.role, users.display_name COLLATE NOCASE
        """,
        (_positive_id(organization_id, "Organization ID"),),
    ).fetchall()
    return [dict(row) for row in rows]
