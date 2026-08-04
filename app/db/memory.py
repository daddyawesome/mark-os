from __future__ import annotations

import sqlite3

from app.db.schema import ensure_column


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_type TEXT NOT NULL,
    memory_key TEXT NOT NULL UNIQUE,
    memory_value TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 5 CHECK(importance BETWEEN 1 AND 10),
    source TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    source_type TEXT,
    source_id INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0
        CHECK(confidence BETWEEN 0.0 AND 1.0),
    sensitivity TEXT NOT NULL DEFAULT 'normal'
        CHECK(sensitivity IN ('normal', 'private', 'restricted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    superseded_by INTEGER,
    last_used_at TEXT,
    content_hash TEXT,
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
"""


INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_timeline_events_date
ON timeline_events(event_date);

CREATE INDEX IF NOT EXISTS idx_timeline_events_type
ON timeline_events(event_type);

CREATE INDEX IF NOT EXISTS idx_memories_type
ON memories(memory_type);

CREATE INDEX IF NOT EXISTS idx_memories_active_importance
ON memories(active, importance DESC, updated_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_memories_source_reference
ON memories(source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_memories_content_hash
ON memories(content_hash)
WHERE content_hash IS NOT NULL;
"""


def migrate(db: sqlite3.Connection) -> None:
    """Add Phase 5.3 structured-memory fields without replacing existing data."""
    ensure_column(db, "memories", "source_type", "TEXT")
    ensure_column(db, "memories", "source_id", "INTEGER")
    ensure_column(
        db,
        "memories",
        "confidence",
        "REAL NOT NULL DEFAULT 1.0 CHECK(confidence BETWEEN 0.0 AND 1.0)",
    )
    ensure_column(
        db,
        "memories",
        "sensitivity",
        (
            "TEXT NOT NULL DEFAULT 'normal' "
            "CHECK(sensitivity IN ('normal', 'private', 'restricted'))"
        ),
    )
    ensure_column(
        db,
        "memories",
        "version",
        "INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1)",
    )
    ensure_column(db, "memories", "superseded_by", "INTEGER")
    ensure_column(db, "memories", "last_used_at", "TEXT")
    ensure_column(db, "memories", "content_hash", "TEXT")


def seed(db: sqlite3.Connection) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO memories
        (memory_type, memory_key, memory_value, importance, source)
        VALUES ('product_principle', 'phase_4_revised_dod', ?, 9, 'phase_4_revised')
        """,
        (
            "A quest can be created, opened, started, blocked, updated, and completed. "
            "Updates preserve progress, notes, minutes, and timestamp history. "
            "Completion requires a result, records evidence and actual time, creates a "
            "timeline event, and awards immutable XP exactly once in a transaction. "
            "Hidden threshold crossing records level-up history.",
        ),
    )
