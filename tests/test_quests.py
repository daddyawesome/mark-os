import sqlite3

import pytest

from app.services.quests import (
    clamp_progress,
    complete_quest,
    normalize_minutes,
    set_quest_status,
    update_quest_progress,
)


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE game_state (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            level INTEGER NOT NULL,
            xp_total INTEGER,
            xp_into_level INTEGER NOT NULL DEFAULT 0,
            character_class TEXT NOT NULL,
            threshold_mode TEXT NOT NULL DEFAULT 'hidden',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_level_up_at TEXT,
            source TEXT NOT NULL DEFAULT 'test',
            notes TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            goal_id INTEGER,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'backlog',
            priority INTEGER NOT NULL DEFAULT 5,
            estimated_minutes INTEGER,
            actual_minutes INTEGER NOT NULL DEFAULT 0,
            energy_required INTEGER NOT NULL DEFAULT 3,
            due_date TEXT,
            difficulty TEXT NOT NULL DEFAULT 'normal',
            xp_reward INTEGER NOT NULL DEFAULT 25,
            progress INTEGER NOT NULL DEFAULT 0,
            quest_source TEXT NOT NULL DEFAULT 'manual',
            why TEXT NOT NULL DEFAULT '',
            blocked_reason TEXT NOT NULL DEFAULT '',
            result_notes TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '',
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE quest_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            progress INTEGER,
            actual_minutes INTEGER,
            session_minutes INTEGER,
            blocker_reason TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL DEFAULT 'update',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
        CREATE TABLE xp_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL UNIQUE,
            event_key TEXT,
            event_type TEXT NOT NULL DEFAULT 'quest_completed',
            source_type TEXT NOT NULL DEFAULT 'quest',
            source_id INTEGER,
            source_title TEXT NOT NULL DEFAULT '',
            xp_delta INTEGER NOT NULL,
            level_before INTEGER NOT NULL,
            level_after INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX idx_xp_ledger_event_key ON xp_ledger(event_key) WHERE event_key IS NOT NULL;
        CREATE TABLE timeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'completed',
            importance INTEGER NOT NULL DEFAULT 5,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE game_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            level INTEGER NOT NULL,
            xp_total INTEGER,
            event TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    db.execute(
        "INSERT INTO game_state (id, level, xp_total, xp_into_level, character_class) VALUES (1, 3, 0, 0, 'Tester')"
    )
    cur = db.execute(
        """
        INSERT INTO tasks
        (title, status, estimated_minutes, difficulty, xp_reward, progress)
        VALUES ('Test quest', 'backlog', 60, 'hard', 50, 0)
        """
    )
    # M9_TEST_OWNERSHIP_TABLES
    for table_name in (
        "tasks",
        "quest_updates",
        "xp_ledger",
        "game_state",
        "timeline_events",
        "game_history",
    ):
        columns = {
            row["name"]
            for row in db.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()
        }
        if "user_id" not in columns:
            db.execute(
                f"ALTER TABLE {table_name} "
                "ADD COLUMN user_id INTEGER"
            )
        db.execute(
            f"UPDATE {table_name} "
            "SET user_id = 0 "
            "WHERE user_id IS NULL"
        )

    return db, cur.lastrowid


def test_progress_and_minutes_are_append_only_and_accumulated():
    db, quest_id = make_db()
    set_quest_status(db, quest_id=quest_id, status="active")
    update_quest_progress(db, quest_id=quest_id, note="first", progress=30, session_minutes=25)
    update_quest_progress(db, quest_id=quest_id, note="second", progress=70, session_minutes=40)

    quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
    assert quest["progress"] == 70
    assert quest["actual_minutes"] == 65
    assert db.execute("SELECT COUNT(*) AS count FROM quest_updates WHERE task_id = ?", (quest_id,)).fetchone()["count"] == 3


def test_blocker_is_recorded_and_can_be_unblocked():
    db, quest_id = make_db()
    set_quest_status(db, quest_id=quest_id, status="blocked", blocker_reason="Railway failed")
    quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
    assert quest["status"] == "blocked"
    assert quest["blocked_reason"] == "Railway failed"

    set_quest_status(db, quest_id=quest_id, status="active")
    quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
    assert quest["status"] == "active"
    assert quest["blocked_reason"] == ""


def test_completion_requires_result():
    db, quest_id = make_db()
    with pytest.raises(ValueError):
        complete_quest(db, quest_id=quest_id, result_notes="", evidence="", session_minutes=10)


def test_completion_awards_xp_once_and_creates_timeline_event():
    db, quest_id = make_db()
    result = complete_quest(
        db,
        quest_id=quest_id,
        result_notes="Deployed to Railway",
        evidence="commit abc123",
        session_minutes=15,
    )
    assert result.xp_awarded == 50
    assert result.duplicate_award is False

    duplicate = complete_quest(
        db,
        quest_id=quest_id,
        result_notes="Retry",
        evidence="",
        session_minutes=15,
    )
    assert duplicate.xp_awarded == 0
    assert duplicate.duplicate_award is True
    assert db.execute("SELECT COUNT(*) AS count FROM xp_ledger").fetchone()["count"] == 1
    assert db.execute("SELECT COUNT(*) AS count FROM timeline_events WHERE event_type = 'quest_completed'").fetchone()["count"] == 1


def test_completion_can_cross_multiple_levels_and_records_each_level():
    db, quest_id = make_db()
    db.execute("UPDATE tasks SET xp_reward = 500 WHERE id = ?", (quest_id,))
    result = complete_quest(db, quest_id=quest_id, result_notes="Epic shipped", evidence="", session_minutes=10)
    assert result.level_after > 4
    assert result.levels_gained >= 2
    assert db.execute("SELECT COUNT(*) AS count FROM game_history").fetchone()["count"] == result.levels_gained
    assert db.execute("SELECT COUNT(*) AS count FROM timeline_events WHERE event_type = 'level_up'").fetchone()["count"] == result.levels_gained


def test_validation_helpers():
    assert clamp_progress(-5) == 0
    assert clamp_progress(150) == 99
    assert clamp_progress(150, complete_allowed=True) == 100
    assert normalize_minutes(-1) is None
    assert normalize_minutes(0) == 0
    assert normalize_minutes(25) == 25
