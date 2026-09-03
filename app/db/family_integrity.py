from __future__ import annotations

import sqlite3


TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_directions_match_checkin_insert
BEFORE INSERT ON directions
WHEN NEW.user_id IS NOT NULL AND NEW.user_id != (
    SELECT user_id FROM checkins WHERE id = NEW.checkin_id
)
BEGIN
    SELECT RAISE(ABORT, 'direction owner must match check-in owner');
END;

CREATE TRIGGER IF NOT EXISTS trg_directions_match_checkin_update
BEFORE UPDATE OF user_id, checkin_id ON directions
WHEN NEW.user_id IS NOT NULL AND NEW.user_id != (
    SELECT user_id FROM checkins WHERE id = NEW.checkin_id
)
BEGIN
    SELECT RAISE(ABORT, 'direction owner must match check-in owner');
END;

CREATE TRIGGER IF NOT EXISTS trg_quest_updates_match_task_insert
BEFORE INSERT ON quest_updates
WHEN NEW.user_id IS NOT NULL AND NEW.user_id != (
    SELECT user_id FROM tasks WHERE id = NEW.task_id
)
BEGIN
    SELECT RAISE(ABORT, 'quest update owner must match task owner');
END;

CREATE TRIGGER IF NOT EXISTS trg_quest_updates_match_task_update
BEFORE UPDATE OF user_id, task_id ON quest_updates
WHEN NEW.user_id IS NOT NULL AND NEW.user_id != (
    SELECT user_id FROM tasks WHERE id = NEW.task_id
)
BEGIN
    SELECT RAISE(ABORT, 'quest update owner must match task owner');
END;

CREATE TRIGGER IF NOT EXISTS trg_xp_match_task_insert
BEFORE INSERT ON xp_ledger
WHEN NEW.user_id IS NOT NULL AND NEW.user_id != (
    SELECT user_id FROM tasks WHERE id = NEW.task_id
)
BEGIN
    SELECT RAISE(ABORT, 'XP owner must match task owner');
END;

CREATE TRIGGER IF NOT EXISTS trg_xp_match_task_update
BEFORE UPDATE OF user_id, task_id ON xp_ledger
WHEN NEW.user_id IS NOT NULL AND NEW.user_id != (
    SELECT user_id FROM tasks WHERE id = NEW.task_id
)
BEGIN
    SELECT RAISE(ABORT, 'XP owner must match task owner');
END;

CREATE TRIGGER IF NOT EXISTS trg_chat_messages_match_session_insert
BEFORE INSERT ON chat_messages
WHEN NEW.user_id IS NOT NULL AND NEW.user_id != (
    SELECT user_id FROM chat_sessions WHERE id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'chat message owner must match session owner');
END;

CREATE TRIGGER IF NOT EXISTS trg_chat_messages_match_session_update
BEFORE UPDATE OF user_id, session_id ON chat_messages
WHEN NEW.user_id IS NOT NULL AND NEW.user_id != (
    SELECT user_id FROM chat_sessions WHERE id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'chat message owner must match session owner');
END;

CREATE TRIGGER IF NOT EXISTS trg_agent_runs_match_chat_insert
BEFORE INSERT ON agent_runs
WHEN NEW.user_id IS NOT NULL
 AND (
    NEW.session_id IS NOT NULL
    AND NEW.user_id != (
        SELECT user_id FROM chat_sessions WHERE id = NEW.session_id
    )
 )
 OR (
    NEW.user_message_id IS NOT NULL
    AND NEW.user_id != (
        SELECT user_id FROM chat_messages WHERE id = NEW.user_message_id
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'agent run owner must match chat owner');
END;

CREATE TRIGGER IF NOT EXISTS trg_agent_steps_match_run_insert
BEFORE INSERT ON agent_steps
WHEN NEW.user_id IS NOT NULL AND NEW.user_id != (
    SELECT user_id FROM agent_runs WHERE id = NEW.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'agent step owner must match run owner');
END;
"""

TRIGGER_NAMES = ('trg_goals_require_owner', 'trg_projects_require_owner', 'trg_checkins_require_owner', 'trg_tasks_require_owner', 'trg_memories_require_owner', 'trg_timeline_require_owner', 'trg_chat_sessions_require_owner', 'trg_directions_match_checkin_insert', 'trg_directions_match_checkin_update', 'trg_quest_updates_match_task_insert', 'trg_quest_updates_match_task_update', 'trg_xp_match_task_insert', 'trg_xp_match_task_update', 'trg_chat_messages_match_session_insert', 'trg_chat_messages_match_session_update', 'trg_agent_runs_match_chat_insert', 'trg_agent_steps_match_run_insert')

REQUIRED_USER_ID_TABLES = (
    "profile", "goals", "projects", "checkins", "directions", "game_state",
    "game_history", "tasks", "quest_updates", "xp_ledger", "memories",
    "memory_candidates", "memory_audit_events", "timeline_events",
    "chat_sessions", "chat_messages", "agent_runs", "agent_steps",
)


def _has_user_id(
    db: sqlite3.Connection,
    table_name: str,
) -> bool:
    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if table is None:
        return False

    columns = {
        row["name"]
        for row in db.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }
    return "user_id" in columns


def ownership_schema_ready(
    db: sqlite3.Connection,
) -> bool:
    return all(
        _has_user_id(db, table_name)
        for table_name in REQUIRED_USER_ID_TABLES
    )


def drop_triggers(db: sqlite3.Connection) -> None:
    for trigger_name in TRIGGER_NAMES:
        db.execute(
            f"DROP TRIGGER IF EXISTS {trigger_name}"
        )


def create_triggers(db: sqlite3.Connection) -> None:
    if not ownership_schema_ready(db):
        return
    db.executescript(TRIGGER_SQL)


def validate_triggers(db: sqlite3.Connection) -> None:
    if not ownership_schema_ready(db):
        return
    expected = {
        "trg_directions_match_checkin_insert",
        "trg_directions_match_checkin_update",
        "trg_quest_updates_match_task_insert",
        "trg_quest_updates_match_task_update",
        "trg_xp_match_task_insert",
        "trg_xp_match_task_update",
        "trg_chat_messages_match_session_insert",
        "trg_chat_messages_match_session_update",
        "trg_agent_runs_match_chat_insert",
        "trg_agent_steps_match_run_insert",
    }
    found = {
        row["name"]
        for row in db.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'trigger'
            """
        ).fetchall()
    }
    missing = expected - found
    if missing:
        raise RuntimeError(
            "Missing M9 ownership triggers: "
            + ", ".join(sorted(missing))
        )
