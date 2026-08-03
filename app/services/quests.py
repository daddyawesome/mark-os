from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from app.services.gamification import apply_xp

VALID_QUEST_STATUSES = {"backlog", "active", "blocked", "completed", "abandoned"}


@dataclass(frozen=True)
class QuestCompletionResult:
    quest_id: int
    xp_awarded: int
    level_before: int
    level_after: int
    levels_gained: int
    levels_crossed: tuple[int, ...]
    duplicate_award: bool = False


def clamp_progress(value: int | None, *, complete_allowed: bool = False) -> int:
    upper = 100 if complete_allowed else 99
    try:
        number = int(value if value is not None else 0)
    except (TypeError, ValueError):
        number = 0
    return max(0, min(upper, number))


def normalize_minutes(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    return minutes if minutes >= 0 else None


def normalize_status(value: str) -> str:
    status = (value or "backlog").strip().lower()
    return status if status in VALID_QUEST_STATUSES else "backlog"


def _require_core_quest_mutation(quest: sqlite3.Row) -> None:
    """Keep CRM-linked quests canonical to the lead service, even for API callers."""
    if quest["quest_source"] == "client_hunting":
        raise ValueError("Client Hunting quests must be managed through the CRM")


def _total_minutes(db: sqlite3.Connection, quest_id: int) -> int:
    row = db.execute(
        """
        SELECT COALESCE(SUM(COALESCE(session_minutes, actual_minutes, 0)), 0) AS total
        FROM quest_updates
        WHERE task_id = ?
        """,
        (quest_id,),
    ).fetchone()
    return int(row["total"] if row else 0)


def record_quest_update(
    db: sqlite3.Connection,
    *,
    quest_id: int,
    event_type: str,
    note: str = "",
    progress: int | None = None,
    session_minutes: int | None = None,
    blocker_reason: str = "",
) -> None:
    safe_minutes = normalize_minutes(session_minutes)
    db.execute(
        """
        INSERT INTO quest_updates
        (task_id, note, progress, actual_minutes, session_minutes, blocker_reason, event_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            quest_id,
            note.strip(),
            progress,
            safe_minutes,
            safe_minutes,
            blocker_reason.strip(),
            event_type,
        ),
    )


def set_quest_status(
    db: sqlite3.Connection,
    *,
    quest_id: int,
    status: str,
    note: str = "",
    blocker_reason: str = "",
) -> None:
    safe_status = normalize_status(status)
    quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
    if not quest:
        raise ValueError("Quest not found")
    _require_core_quest_mutation(quest)
    if quest["status"] == "completed":
        return

    if safe_status == "active":
        db.execute(
            """
            UPDATE tasks
            SET status = 'active',
                blocked_reason = '',
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (quest_id,),
        )
        record_quest_update(
            db,
            quest_id=quest_id,
            event_type="started" if not quest["started_at"] else "unblocked",
            note=note or "Quest started.",
            progress=quest["progress"],
        )
    elif safe_status == "blocked":
        reason = blocker_reason.strip() or note.strip() or "Blocked."
        db.execute(
            """
            UPDATE tasks
            SET status = 'blocked',
                blocked_reason = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (reason, quest_id),
        )
        record_quest_update(
            db,
            quest_id=quest_id,
            event_type="blocked",
            note=note or reason,
            progress=quest["progress"],
            blocker_reason=reason,
        )
    elif safe_status == "abandoned":
        db.execute(
            """
            UPDATE tasks
            SET status = 'abandoned', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (quest_id,),
        )
        record_quest_update(
            db,
            quest_id=quest_id,
            event_type="abandoned",
            note=note or "Quest abandoned.",
            progress=quest["progress"],
        )


def update_quest_progress(
    db: sqlite3.Connection,
    *,
    quest_id: int,
    note: str,
    progress: int,
    session_minutes: int | None = None,
) -> int:
    safe_progress = clamp_progress(progress, complete_allowed=False)
    safe_minutes = normalize_minutes(session_minutes)
    quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
    if not quest:
        raise ValueError("Quest not found")
    _require_core_quest_mutation(quest)
    if quest["status"] == "completed":
        return int(quest["progress"] or 100)

    db.execute(
        """
        UPDATE tasks
        SET status = CASE WHEN status = 'blocked' THEN status ELSE 'active' END,
            progress = ?,
            actual_minutes = COALESCE(actual_minutes, 0) + COALESCE(?, 0),
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (safe_progress, safe_minutes, quest_id),
    )
    record_quest_update(
        db,
        quest_id=quest_id,
        event_type="update",
        note=note,
        progress=safe_progress,
        session_minutes=safe_minutes,
    )
    return safe_progress


def complete_quest(
    db: sqlite3.Connection,
    *,
    quest_id: int,
    result_notes: str,
    evidence: str = "",
    session_minutes: int | None = None,
) -> QuestCompletionResult:
    """Complete a quest, award immutable XP exactly once, and record memory events.

    Caller should execute this inside one database transaction. The get_db() context
    manager already commits or rolls back the whole operation.
    """
    result = result_notes.strip()
    if not result:
        raise ValueError("Completion result is required")

    safe_minutes = normalize_minutes(session_minutes)
    quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
    if not quest:
        raise ValueError("Quest not found")
    _require_core_quest_mutation(quest)

    state = db.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
    level_before = int(state["level"] if state else 1)
    xp_total_before = state["xp_total"] if state else None
    xp_into_level_before = int(state["xp_into_level"] if state else 0)
    xp_reward = max(0, int(quest["xp_reward"] or 0))
    event_key = f"quest_completed:{quest_id}"

    existing_award = db.execute(
        "SELECT * FROM xp_ledger WHERE event_key = ? OR task_id = ?",
        (event_key, quest_id),
    ).fetchone()

    if quest["status"] != "completed":
        db.execute(
            """
            UPDATE tasks
            SET status = 'completed',
                progress = 100,
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                result_notes = ?,
                evidence = ?,
                actual_minutes = COALESCE(actual_minutes, 0) + COALESCE(?, 0),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (result, evidence.strip(), safe_minutes, quest_id),
        )
        record_quest_update(
            db,
            quest_id=quest_id,
            event_type="completed",
            note=result,
            progress=100,
            session_minutes=safe_minutes,
        )

    if existing_award:
        return QuestCompletionResult(
            quest_id=quest_id,
            xp_awarded=0,
            level_before=level_before,
            level_after=int(existing_award["level_after"]),
            levels_gained=0,
            levels_crossed=(),
            duplicate_award=True,
        )

    award = apply_xp(
        level=level_before,
        xp_total=xp_total_before,
        xp_into_level=xp_into_level_before,
        awarded_xp=xp_reward,
    )

    db.execute(
        """
        INSERT INTO xp_ledger
        (task_id, event_key, event_type, source_type, source_id, source_title,
         xp_delta, level_before, level_after, reason)
        VALUES (?, ?, 'quest_completed', 'quest', ?, ?, ?, ?, ?, ?)
        """,
        (
            quest_id,
            event_key,
            quest_id,
            quest["title"],
            xp_reward,
            level_before,
            award.level,
            f"Completed quest: {quest['title']}",
        ),
    )

    db.execute(
        """
        UPDATE game_state
        SET level = ?,
            xp_total = ?,
            xp_into_level = ?,
            updated_at = CURRENT_TIMESTAMP,
            last_level_up_at = CASE WHEN ? > 0 THEN CURRENT_TIMESTAMP ELSE last_level_up_at END,
            source = 'quest_engine'
        WHERE id = 1
        """,
        (award.level, award.xp_total, award.xp_into_level, award.levels_gained),
    )

    db.execute(
        """
        INSERT INTO timeline_events
        (event_date, event_type, title, summary, details_json, status, importance, source)
        VALUES (date('now', 'localtime'), 'quest_completed', ?, ?, ?, 'completed', 8, 'quest_engine')
        """,
        (
            quest["title"],
            result,
            json.dumps(
                {
                    "task_id": quest_id,
                    "xp_awarded": xp_reward,
                    "level_before": level_before,
                    "level_after": award.level,
                    "evidence": evidence.strip(),
                    "estimated_minutes": quest["estimated_minutes"],
                    "actual_minutes": _total_minutes(db, quest_id),
                }
            ),
        ),
    )

    for crossed_level in award.levels_crossed:
        db.execute(
            """
            INSERT INTO game_history
            (event_date, level, xp_total, event, source)
            VALUES (date('now', 'localtime'), ?, ?, ?, 'quest_engine')
            """,
            (
                crossed_level,
                award.xp_total,
                f"Reached Level {crossed_level} after completing: {quest['title']}",
            ),
        )
        db.execute(
            """
            INSERT INTO timeline_events
            (event_date, event_type, title, summary, details_json, status, importance, source)
            VALUES (date('now', 'localtime'), 'level_up', ?, ?, ?, 'completed', 10, 'quest_engine')
            """,
            (
                f"Reached Level {crossed_level}",
                "Quest progress crossed a hidden level threshold.",
                json.dumps(
                    {
                        "quest_id": quest_id,
                        "quest_title": quest["title"],
                        "level_before": level_before,
                        "level_after": award.level,
                        "crossed_level": crossed_level,
                        "levels_gained": award.levels_gained,
                    }
                ),
            ),
        )

    return QuestCompletionResult(
        quest_id=quest_id,
        xp_awarded=xp_reward,
        level_before=level_before,
        level_after=award.level,
        levels_gained=award.levels_gained,
        levels_crossed=award.levels_crossed,
        duplicate_award=False,
    )
