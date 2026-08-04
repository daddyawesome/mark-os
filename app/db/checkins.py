from __future__ import annotations

import sqlite3

from app.db.schema import ensure_column


SCHEMA_SQL = """
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
"""


INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_checkins_date
ON checkins(checkin_date);
"""


def migrate(db: sqlite3.Connection) -> None:
    ensure_column(db, "checkins", "cash_in", "REAL")
    ensure_column(db, "checkins", "updated_at", "TEXT")
    db.execute(
        """
        UPDATE checkins
        SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
        WHERE updated_at IS NULL OR updated_at = ''
        """
    )

