from __future__ import annotations

import sqlite3

from app.db.schema import ensure_column


GAME_SCHEMA_SQL = """
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
"""


QUEST_SCHEMA_SQL = """
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
"""


INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_tasks_status
ON tasks(status);

CREATE INDEX IF NOT EXISTS idx_tasks_project
ON tasks(project_id);

CREATE INDEX IF NOT EXISTS idx_tasks_goal
ON tasks(goal_id);

CREATE INDEX IF NOT EXISTS idx_quest_updates_task
ON quest_updates(task_id);
"""


def migrate_game_state(db: sqlite3.Connection) -> None:
    ensure_column(db, "game_state", "xp_into_level", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(db, "game_state", "last_level_up_at", "TEXT")


def migrate_quest_tables(db: sqlite3.Connection) -> None:
    ensure_column(db, "tasks", "goal_id", "INTEGER REFERENCES goals(id)")
    ensure_column(db, "tasks", "difficulty", "TEXT NOT NULL DEFAULT 'normal'")
    ensure_column(db, "tasks", "xp_reward", "INTEGER NOT NULL DEFAULT 25")
    ensure_column(db, "tasks", "progress", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(db, "tasks", "started_at", "TEXT")
    ensure_column(db, "tasks", "result_notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "tasks", "actual_minutes", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(db, "tasks", "energy_required", "INTEGER NOT NULL DEFAULT 3")
    ensure_column(db, "tasks", "quest_source", "TEXT NOT NULL DEFAULT 'manual'")
    ensure_column(db, "tasks", "why", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "tasks", "blocked_reason", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "tasks", "evidence", "TEXT NOT NULL DEFAULT ''")
    # SQLite does not allow ALTER TABLE ADD COLUMN with a non-constant
    # CURRENT_TIMESTAMP default. Add it plainly, then backfill existing rows.
    ensure_column(db, "tasks", "updated_at", "TEXT")
    db.execute(
        """
        UPDATE tasks
        SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
        WHERE updated_at IS NULL OR updated_at = ''
        """
    )

    ensure_column(db, "quest_updates", "session_minutes", "INTEGER")
    ensure_column(db, "quest_updates", "blocker_reason", "TEXT NOT NULL DEFAULT ''")

    ensure_column(db, "xp_ledger", "event_key", "TEXT")
    ensure_column(
        db,
        "xp_ledger",
        "event_type",
        "TEXT NOT NULL DEFAULT 'quest_completed'",
    )
    ensure_column(db, "xp_ledger", "source_type", "TEXT NOT NULL DEFAULT 'quest'")
    ensure_column(db, "xp_ledger", "source_id", "INTEGER")
    ensure_column(db, "xp_ledger", "source_title", "TEXT NOT NULL DEFAULT ''")


def create_unique_indexes(db: sqlite3.Connection) -> None:
    # Create this index only after event_key is guaranteed to exist.
    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_xp_ledger_event_key
        ON xp_ledger(event_key)
        WHERE event_key IS NOT NULL
        """
    )


def backfill(db: sqlite3.Connection) -> None:
    db.execute(
        """
        UPDATE xp_ledger
        SET event_key = COALESCE(event_key, 'quest_completed:' || task_id),
            source_id = COALESCE(source_id, task_id),
            source_title = COALESCE(NULLIF(source_title, ''), reason)
        WHERE task_id IS NOT NULL
        """
    )


def seed(db: sqlite3.Connection) -> None:
    # Imported history keeps Level 3 because this only inserts when no state exists.
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
    if task_count != 0:
        return

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
            "Push Phase 4 revised Quest Engine and verify progress history, blockers, "
            "result-required completion, immutable XP, and Level 3 persistence online.",
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
            "Find one real buyer showing a reporting, Excel, Power BI, SQL, or "
            "automation pain and send one tailored message.",
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
