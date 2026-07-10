from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("MARK_OS_DB_PATH", str(DATA_DIR / "mark_os.db")))


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _column_names(db: sqlite3.Connection, table_name: str) -> set[str]:
    rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _table_exists(db: sqlite3.Connection, table_name: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_column(
    db: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    if _table_exists(db, table_name) and column_name not in _column_names(db, table_name):
        db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def init_db() -> None:
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                name TEXT NOT NULL,
                wealth_goal TEXT NOT NULL,
                weekday_hours TEXT NOT NULL,
                weekend_rule TEXT NOT NULL,
                strongest_skills TEXT NOT NULL,
                primary_blocker TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                priority INTEGER NOT NULL DEFAULT 5,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                purpose TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                priority INTEGER NOT NULL DEFAULT 5,
                progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
                next_action TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checkin_date TEXT NOT NULL DEFAULT (date('now', 'localtime')),
                cash REAL,
                expenses REAL NOT NULL DEFAULT 0,
                free_hours REAL NOT NULL DEFAULT 0,
                energy INTEGER NOT NULL DEFAULT 3 CHECK(energy BETWEEN 1 AND 5),
                accomplished TEXT NOT NULL DEFAULT '',
                blocker TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS directions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checkin_id INTEGER NOT NULL,
                main_quest TEXT NOT NULL,
                why TEXT NOT NULL,
                side_quest_1 TEXT NOT NULL,
                side_quest_2 TEXT NOT NULL,
                avoid TEXT NOT NULL,
                signal TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (checkin_id) REFERENCES checkins(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                level INTEGER NOT NULL DEFAULT 1 CHECK(level >= 1),
                xp_total INTEGER,
                character_class TEXT NOT NULL,
                threshold_mode TEXT NOT NULL DEFAULT 'hidden',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                source TEXT NOT NULL DEFAULT 'system',
                notes TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS game_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_date TEXT NOT NULL,
                level INTEGER NOT NULL CHECK(level >= 1),
                xp_total INTEGER,
                event TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_type TEXT NOT NULL,
                memory_key TEXT NOT NULL UNIQUE,
                memory_value TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 5 CHECK(importance BETWEEN 1 AND 10),
                source TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS timeline_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_date TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'completed',
                importance INTEGER NOT NULL DEFAULT 5 CHECK(importance BETWEEN 1 AND 10),
                source TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS system_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                goal_id INTEGER,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'backlog',
                priority INTEGER NOT NULL DEFAULT 5,
                estimated_minutes INTEGER,
                actual_minutes INTEGER NOT NULL DEFAULT 0,
                energy_required INTEGER NOT NULL DEFAULT 3 CHECK(energy_required BETWEEN 1 AND 5),
                due_date TEXT,
                difficulty TEXT NOT NULL DEFAULT 'normal',
                xp_reward INTEGER NOT NULL DEFAULT 25,
                progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
                quest_source TEXT NOT NULL DEFAULT 'manual',
                why TEXT NOT NULL DEFAULT '',
                blocked_reason TEXT NOT NULL DEFAULT '',
                result_notes TEXT NOT NULL DEFAULT '',
                evidence TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
                FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS quest_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                progress INTEGER,
                actual_minutes INTEGER,
                session_minutes INTEGER,
                blocker_reason TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT 'update',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS xp_ledger (
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_checkins_date ON checkins(checkin_date);
            CREATE INDEX IF NOT EXISTS idx_timeline_events_date ON timeline_events(event_date);
            CREATE INDEX IF NOT EXISTS idx_timeline_events_type ON timeline_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_goal ON tasks(goal_id);
            CREATE INDEX IF NOT EXISTS idx_quest_updates_task ON quest_updates(task_id);
            """
        )

        # Safe migrations for the already-live Railway SQLite database.
        _ensure_column(db, "game_state", "xp_into_level", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "game_state", "last_level_up_at", "TEXT")

        _ensure_column(db, "projects", "goal_id", "INTEGER REFERENCES goals(id)")

        _ensure_column(db, "tasks", "goal_id", "INTEGER REFERENCES goals(id)")
        _ensure_column(db, "tasks", "difficulty", "TEXT NOT NULL DEFAULT 'normal'")
        _ensure_column(db, "tasks", "xp_reward", "INTEGER NOT NULL DEFAULT 25")
        _ensure_column(db, "tasks", "progress", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "tasks", "started_at", "TEXT")
        _ensure_column(db, "tasks", "result_notes", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "tasks", "actual_minutes", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "tasks", "energy_required", "INTEGER NOT NULL DEFAULT 3")
        _ensure_column(db, "tasks", "quest_source", "TEXT NOT NULL DEFAULT 'manual'")
        _ensure_column(db, "tasks", "why", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "tasks", "blocked_reason", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "tasks", "evidence", "TEXT NOT NULL DEFAULT ''")
        # SQLite does not allow ALTER TABLE ADD COLUMN with a
        # non-constant CURRENT_TIMESTAMP default. Add the column plainly,
        # then backfill existing rows in a separate statement.
        _ensure_column(db, "tasks", "updated_at", "TEXT")

        db.execute(
            """
            UPDATE tasks
            SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
            WHERE updated_at IS NULL OR updated_at = ''
            """
        )

        _ensure_column(db, "quest_updates", "session_minutes", "INTEGER")
        _ensure_column(db, "quest_updates", "blocker_reason", "TEXT NOT NULL DEFAULT ''")

        _ensure_column(db, "xp_ledger", "event_key", "TEXT")
        _ensure_column(db, "xp_ledger", "event_type", "TEXT NOT NULL DEFAULT 'quest_completed'")
        _ensure_column(db, "xp_ledger", "source_type", "TEXT NOT NULL DEFAULT 'quest'")
        _ensure_column(db, "xp_ledger", "source_id", "INTEGER")
        _ensure_column(db, "xp_ledger", "source_title", "TEXT NOT NULL DEFAULT ''")

        # Create this index only after event_key is guaranteed to exist.
        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_xp_ledger_event_key
            ON xp_ledger(event_key)
            WHERE event_key IS NOT NULL
            """
        )

        # Backfill event keys for any XP rows created by the earlier Quest Engine patch.
        db.execute(
            """
            UPDATE xp_ledger
            SET event_key = COALESCE(event_key, 'quest_completed:' || task_id),
                source_id = COALESCE(source_id, task_id),
                source_title = COALESCE(NULLIF(source_title, ''), reason)
            WHERE task_id IS NOT NULL
            """
        )

        db.execute(
            """
            INSERT OR IGNORE INTO profile
            (id, name, wealth_goal, weekday_hours, weekend_rule, strongest_skills, primary_blocker)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Mark",
                "Build a business that reaches at least USD 10,000/month and eventually supports a team.",
                "2-3 focused hours on weekdays",
                "Protect weekends for family whenever possible",
                "Python, SQL, Power BI, data engineering, automation",
                "Finding qualified clients and turning skills into consistent revenue",
            ),
        )

        seed_goals = [
            ("Reach USD 10,000/month in business income", "wealth", 10),
            ("Build a business with a team", "business", 9),
            ("Create a flagship portfolio product", "career", 8),
            ("Protect family weekends", "family", 10),
        ]
        for title, category, priority in seed_goals:
            db.execute(
                """
                INSERT INTO goals (title, category, priority)
                SELECT ?, ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM goals WHERE title = ?)
                """,
                (title, category, priority, title),
            )

        db.execute(
            """
            INSERT OR IGNORE INTO projects
            (name, purpose, status, priority, progress, next_action)
            VALUES (?, ?, 'active', ?, ?, ?)
            """,
            (
                "MARK OS v0.1",
                "Build a personal operating system that observes current reality and gives the highest-leverage next action.",
                10,
                10,
                "Finish the revised Quest Engine, then add budget-safe AI chat.",
            ),
        )

        # Imported history keeps Level 3 because this only inserts when no game state exists.
        db.execute(
            """
            INSERT OR IGNORE INTO game_state
            (id, level, xp_total, xp_into_level, character_class, threshold_mode, source, notes)
            VALUES (1, 1, NULL, 0, ?, 'hidden', 'system', ?)
            """,
            (
                "Data Builder / Future Business Owner",
                "Default game state. Imported or user-confirmed state takes precedence.",
            ),
        )

        # Seed real next actions only when no quests exist yet.
        task_count = db.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()["count"]
        if task_count == 0:
            mark_os_project = db.execute(
                "SELECT id FROM projects WHERE name LIKE 'MARK OS%' ORDER BY id LIMIT 1"
            ).fetchone()
            project_id = mark_os_project["id"] if mark_os_project else None
            wealth_goal = db.execute(
                "SELECT id FROM goals WHERE title LIKE 'Reach USD 10,000%' LIMIT 1"
            ).fetchone()
            wealth_goal_id = wealth_goal["id"] if wealth_goal else None

            seed_tasks = [
                (
                    project_id,
                    None,
                    "Deploy the revised Quest Engine to Railway",
                    "Push Phase 4 revised Quest Engine and verify progress history, blockers, result-required completion, immutable XP, and Level 3 persistence online.",
                    10,
                    75,
                    4,
                    "hard",
                    50,
                    "system",
                    "This unlocks real execution tracking before the AI chat is added.",
                ),
                (
                    None,
                    wealth_goal_id,
                    "Complete one qualified lead outreach",
                    "Find one real buyer showing a reporting, Excel, Power BI, SQL, or automation pain and send one tailored message.",
                    9,
                    30,
                    3,
                    "hard",
                    50,
                    "system",
                    "Client finding is the recurring blocker and supports the $10,000/month goal.",
                ),
            ]
            db.executemany(
                """
                INSERT INTO tasks
                (project_id, goal_id, title, description, status, priority, estimated_minutes,
                 energy_required, difficulty, xp_reward, progress, quest_source, why)
                VALUES (?, ?, ?, ?, 'backlog', ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                seed_tasks,
            )

        # Add the revised Phase 4 definition of done to project memory once.
        db.execute(
            """
            INSERT OR IGNORE INTO memories
            (memory_type, memory_key, memory_value, importance, source)
            VALUES ('product_principle', 'phase_4_revised_dod', ?, 9, 'phase_4_revised')
            """,
            (
                "A quest can be created, opened, started, blocked, updated, and completed. Updates preserve progress, notes, minutes, and timestamp history. Completion requires a result, records evidence and actual time, creates a timeline event, and awards immutable XP exactly once in a transaction. Hidden threshold crossing records level-up history.",
            ),
        )