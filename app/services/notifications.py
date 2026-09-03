from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Mapping

from app.services.follow_up_command_center import resolve_manila_today
from app.services.lead_work_queues import list_visible_leads


def build_notifications(
    db: sqlite3.Connection,
    user: Mapping[str, Any],
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Build a read-only, permission-scoped notification list."""
    current_date = today or resolve_manila_today(datetime.now(timezone.utc))
    user_id = int(user["id"])
    role = str(user.get("role") or "")
    notifications: list[dict[str, Any]] = []

    if role in {"owner", "member"}:
        checked_in = db.execute(
            "SELECT 1 FROM checkins WHERE user_id = ? AND checkin_date = ? LIMIT 1",
            (user_id, current_date.isoformat()),
        ).fetchone()
        if checked_in is None:
            notifications.append(
                {
                    "kind": "checkin_reminder",
                    "title": "Daily check-in is due",
                    "body": "Record today's state so recommendations use current evidence.",
                    "href": "/",
                    "due_label": "Today",
                }
            )

        overdue = db.execute(
            """
            SELECT id, title, due_date
            FROM tasks
            WHERE user_id = ?
              AND status NOT IN ('completed', 'abandoned', 'closed')
              AND due_date IS NOT NULL
              AND due_date < ?
            ORDER BY due_date, priority DESC, id
            LIMIT 25
            """,
            (user_id, current_date.isoformat()),
        ).fetchall()
        notifications.extend(
            {
                "kind": "overdue_quest",
                "title": str(row["title"]),
                "body": "This quest is overdue.",
                "href": f"/quests/{row['id']}",
                "due_label": str(row["due_date"]),
            }
            for row in overdue
        )

        if current_date.weekday() == 0:
            notifications.append(
                {
                    "kind": "weekly_review_reminder",
                    "title": "Weekly review",
                    "body": "Review recent check-ins and set the week's priorities.",
                    "href": "/history",
                    "due_label": "This week",
                }
            )

    workspace = user.get("current_workspace")
    if role in {"owner", "lead_sourcer", "relationship_manager"} and isinstance(
        workspace, Mapping
    ):
        organization_id = int(workspace["id"])
        for lead in list_visible_leads(
            db, user, organization_id=organization_id
        ):
            due = str(lead["next_action_due_date"] or "")
            if due and due <= current_date.isoformat() and lead["pipeline_status"] not in {
                "won", "lost"
            }:
                notifications.append(
                    {
                        "kind": "lead_next_action_due",
                        "title": str(lead["company"]),
                        "body": str(lead["next_action"] or "Next action is due."),
                        "href": f"/crm/leads/{lead['id']}",
                        "due_label": due,
                    }
                )

    order = {
        "lead_next_action_due": 0,
        "overdue_quest": 1,
        "checkin_reminder": 2,
        "weekly_review_reminder": 3,
    }
    return sorted(
        notifications,
        key=lambda item: (order.get(str(item["kind"]), 99), str(item["due_label"])),
    )
