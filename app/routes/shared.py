from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=APP_DIR / "templates")


def optional_int(value: str | int | None) -> int | None:
    if value is None or not str(value).strip():
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def bounded_int(
    value: str | int | None,
    *,
    default: int,
    low: int,
    high: int,
) -> int:
    number = optional_int(value)
    if number is None:
        number = default
    return max(low, min(high, number))


def _compute_effective_priority(quest: dict) -> float:
    """Blend task priority with project and goal priority for future Director use."""
    task_priority = quest.get("priority") or 5
    project_priority = quest.get("project_priority")
    goal_priority = quest.get("goal_priority")

    weighted = task_priority * 0.5
    weight_total = 0.5
    if project_priority is not None:
        weighted += project_priority * 0.3
        weight_total += 0.3
    if goal_priority is not None:
        weighted += goal_priority * 0.2
        weight_total += 0.2
    return round(weighted / weight_total, 2)


def load_open_quests(db) -> list[dict]:
    rows = db.execute(
        """
        SELECT
            t.*,
            p.name AS project_name,
            p.priority AS project_priority,
            p.goal_id AS project_goal_id,
            COALESCE(gt.priority, gp.priority) AS goal_priority,
            COALESCE(gt.title, gp.title) AS goal_title
        FROM tasks t
        LEFT JOIN projects p ON p.id = t.project_id
        LEFT JOIN goals gt ON gt.id = t.goal_id
        LEFT JOIN goals gp ON gp.id = p.goal_id
        WHERE t.status NOT IN ('completed', 'abandoned', 'closed')
        ORDER BY t.priority DESC, t.id
        """
    ).fetchall()
    quests = [dict(row) for row in rows]
    for quest in quests:
        quest["effective_priority"] = _compute_effective_priority(quest)
    return quests


def load_system_state(db) -> dict:
    game_state = db.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
    return {
        "level": game_state["level"] if game_state else 1,
        "xp_total": game_state["xp_total"] if game_state else None,
        "xp_into_level": game_state["xp_into_level"] if game_state else 0,
        "character_class": (
            game_state["character_class"]
            if game_state
            else "Data Builder / Future Business Owner"
        ),
        "threshold_mode": game_state["threshold_mode"] if game_state else "hidden",
        "memory_count": db.execute(
            "SELECT COUNT(*) AS count FROM memories WHERE active = 1"
        ).fetchone()["count"],
        "timeline_count": db.execute(
            "SELECT COUNT(*) AS count FROM timeline_events"
        ).fetchone()["count"],
        "task_count": db.execute(
            """
            SELECT COUNT(*) AS count FROM tasks
            WHERE status NOT IN ('completed', 'abandoned', 'closed')
            """
        ).fetchone()["count"],
        "blocked_count": db.execute(
            "SELECT COUNT(*) AS count FROM tasks WHERE status = 'blocked'"
        ).fetchone()["count"],
    }
