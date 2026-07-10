from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "mark_os.db"


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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


def _ensure_column(
    db: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    if column_name not in _column_names(db, table_name):
        db.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


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
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'backlog',
                priority INTEGER NOT NULL DEFAULT 5,
                estimated_minutes INTEGER,
                due_date TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS quest_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                progress INTEGER,
                actual_minutes INTEGER,
                event_type TEXT NOT NULL DEFAULT 'update',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS xp_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL UNIQUE,
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
            CREATE INDEX IF NOT EXISTS idx_quest_updates_task ON quest_updates(task_id);
            """
        )

        # Safe migrations for the already-live Railway SQLite database.
        _ensure_column(db, "game_state", "xp_into_level", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "game_state", "last_level_up_at", "TEXT")

        _ensure_column(db, "tasks", "difficulty", "TEXT NOT NULL DEFAULT 'normal'")
        _ensure_column(db, "tasks", "xp_reward", "INTEGER NOT NULL DEFAULT 25")
        _ensure_column(db, "tasks", "progress", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "tasks", "started_at", "TEXT")
        _ensure_column(db, "tasks", "result_notes", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "tasks", "actual_minutes", "INTEGER")

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
                "Deploy the interactive Quest Engine, then add budget-safe AI chat.",
            ),
        )

        # Imported history keeps Level 3 because this only inserts when no game state exists.
        db.execute(
            """
            INSERT OR IGNORE INTO game_state
            (id, level, xp_total, character_class, threshold_mode, source, notes)
            VALUES (1, 1, NULL, ?, 'hidden', 'system', ?)
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

            db.executemany(
                """
                INSERT INTO tasks
                (project_id, title, description, status, priority, estimated_minutes,
                 difficulty, xp_reward, progress)
                VALUES (?, ?, ?, 'backlog', ?, ?, ?, ?, 0)
                """,
                [
                    (
                        project_id,
                        "Deploy the interactive Quest Engine to Railway",
                        "Push the Quest Engine, verify clickable quests, updates, completion, XP, and Level 3 persistence online.",
                        10,
                        45,
                        "hard",
                        50,
                    ),
                    (
                        None,
                        "Complete one qualified lead outreach",
                        "Find one real buyer showing a reporting, Excel, Power BI, SQL, or automation pain and send one tailored message.",
                        9,
                        30,
                        "hard",
                        50,
                    ),
                ],
            )
