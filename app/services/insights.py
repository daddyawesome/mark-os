from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from app.services.lead_work_queues import list_visible_leads
from app.services.follow_up_command_center import resolve_manila_today


def _series(counter: Counter[str]) -> dict[str, list[Any]]:
    labels = sorted(counter)
    return {"labels": labels, "values": [counter[label] for label in labels]}


def build_insights(
    db: sqlite3.Connection,
    user: Mapping[str, Any],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Build read-only personal and CRM trends from permission-scoped rows."""
    current_date = today or resolve_manila_today(datetime.now(timezone.utc))
    role = str(user.get("role") or "")
    user_id = int(user["id"])
    result: dict[str, Any] = {"personal": None, "crm": None}

    if role in {"owner", "member"}:
        cutoff = (current_date - timedelta(days=29)).isoformat()
        checkins = db.execute(
            """
            SELECT checkin_date, energy, free_hours
            FROM checkins
            WHERE user_id = ? AND checkin_date >= ?
            ORDER BY checkin_date, id
            """,
            (user_id, cutoff),
        ).fetchall()
        quest_rows = db.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM tasks WHERE user_id = ? GROUP BY status ORDER BY status
            """,
            (user_id,),
        ).fetchall()
        recommendation_count = db.execute(
            "SELECT COUNT(*) AS count FROM directions WHERE user_id = ?",
            (user_id,),
        ).fetchone()["count"]
        completed_count = db.execute(
            "SELECT COUNT(*) AS count FROM tasks WHERE user_id = ? AND status = 'completed'",
            (user_id,),
        ).fetchone()["count"]
        result["personal"] = {
            "checkin_count": len(checkins),
            "energy": {
                "labels": [str(row["checkin_date"]) for row in checkins],
                "values": [int(row["energy"]) for row in checkins],
            },
            "free_hours": {
                "labels": [str(row["checkin_date"]) for row in checkins],
                "values": [float(row["free_hours"]) for row in checkins],
            },
            "quest_status": {
                "labels": [str(row["status"]) for row in quest_rows],
                "values": [int(row["count"]) for row in quest_rows],
            },
            "recommendations_generated": int(recommendation_count),
            "completed_quests": int(completed_count),
        }

    workspace = user.get("current_workspace")
    if role in {"owner", "lead_sourcer", "relationship_manager"} and isinstance(
        workspace, Mapping
    ):
        visible = list_visible_leads(db, user, organization_id=int(workspace["id"]))
        pipeline = Counter(str(row["pipeline_status"]) for row in visible)
        sources = Counter(str(row["source"] or "Unspecified") for row in visible)
        relationship_ids = [
            int(row["business_development_owner_user_id"])
            for row in visible
            if row["business_development_owner_user_id"] is not None
        ]
        relationship_names: dict[int, str] = {}
        if relationship_ids:
            placeholders = ",".join("?" for _ in set(relationship_ids))
            relationship_names = {
                int(row["id"]): str(row["display_name"])
                for row in db.execute(
                    f"SELECT id, display_name FROM users WHERE id IN ({placeholders})",
                    tuple(sorted(set(relationship_ids))),
                )
            }
        managers = Counter(
            relationship_names.get(manager_id, "Unassigned")
            for manager_id in relationship_ids
        )

        activity = Counter()
        lead_ids = [int(row["id"]) for row in visible]
        if lead_ids:
            placeholders = ",".join("?" for _ in lead_ids)
            cutoff = (current_date - timedelta(days=29)).isoformat()
            for row in db.execute(
                f"""
                SELECT substr(activity_at, 1, 10) AS activity_date,
                       COUNT(*) AS count
                FROM lead_activities
                WHERE lead_id IN ({placeholders})
                  AND deleted_at IS NULL
                  AND substr(activity_at, 1, 10) >= ?
                GROUP BY substr(activity_at, 1, 10)
                ORDER BY activity_date
                """,
                (*lead_ids, cutoff),
            ):
                activity[str(row["activity_date"])] = int(row["count"])

        total = len(visible)
        won = pipeline.get("won", 0)
        result["crm"] = {
            "workspace_name": str(workspace.get("name") or workspace.get("slug")),
            "lead_count": total,
            "won_count": won,
            "conversion_percent": round((won / total * 100), 1) if total else 0.0,
            "pipeline": _series(pipeline),
            "sources": _series(sources),
            "relationship_managers": _series(managers),
            "activity": _series(activity),
        }

    return result
