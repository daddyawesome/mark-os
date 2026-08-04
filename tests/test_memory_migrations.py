from __future__ import annotations

import sqlite3

from app import database


MEMORY_COLUMNS = [
    "id",
    "memory_type",
    "memory_key",
    "memory_value",
    "importance",
    "source",
    "active",
    "source_type",
    "source_id",
    "confidence",
    "sensitivity",
    "version",
    "superseded_by",
    "last_used_at",
    "content_hash",
    "created_at",
    "updated_at",
]

EXPECTED_MEMORY_INDEXES = {
    "idx_memories_type": (False, False, ["memory_type"]),
    "idx_memories_active_importance": (
        False,
        False,
        ["active", "importance", "updated_at", "id"],
    ),
    "idx_memories_source_reference": (
        False,
        False,
        ["source_type", "source_id"],
    ),
    "idx_memories_content_hash": (
        False,
        True,
        ["content_hash"],
    ),
}


def _connect(database_path) -> sqlite3.Connection:
    db = sqlite3.connect(database_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _column_names(db: sqlite3.Connection, table_name: str) -> list[str]:
    return [row["name"] for row in db.execute(f"PRAGMA table_info({table_name})")]


def _assert_memory_columns(db: sqlite3.Connection) -> None:
    """Verify all expected fields without depending on SQLite column order.

    Fresh databases use the CREATE TABLE order. Legacy databases retain their
    original order and append fields added later through ALTER TABLE.
    """
    actual_columns = _column_names(db, "memories")

    assert len(actual_columns) == len(MEMORY_COLUMNS)
    assert set(actual_columns) == set(MEMORY_COLUMNS)


def _index_details(
    db: sqlite3.Connection,
    table_name: str,
    index_name: str,
) -> tuple[bool, bool, list[str]]:
    indexes = {
        row["name"]: row
        for row in db.execute(f"PRAGMA index_list({table_name})").fetchall()
    }
    index = indexes[index_name]
    columns = [
        row["name"]
        for row in db.execute(f"PRAGMA index_info({index_name})").fetchall()
    ]
    return bool(index["unique"]), bool(index["partial"]), columns


def test_fresh_database_has_structured_memory_columns_and_indexes(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "fresh-structured-memory.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    _assert_memory_columns(db)

    columns = {
        row["name"]: row
        for row in db.execute("PRAGMA table_info(memories)").fetchall()
    }
    assert columns["confidence"]["notnull"] == 1
    assert columns["confidence"]["dflt_value"] == "1.0"
    assert columns["sensitivity"]["notnull"] == 1
    assert columns["sensitivity"]["dflt_value"] == "'normal'"
    assert columns["version"]["notnull"] == 1
    assert columns["version"]["dflt_value"] == "1"

    for index_name, expected in EXPECTED_MEMORY_INDEXES.items():
        assert _index_details(db, "memories", index_name) == expected

    content_hash_sql = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'index' AND name = 'idx_memories_content_hash'
        """
    ).fetchone()["sql"]
    normalized_sql = " ".join(content_hash_sql.lower().split()).rstrip(";")
    _, separator, predicate = normalized_sql.partition(" where ")
    assert separator and predicate == "content_hash is not null"

    seed = db.execute(
        "SELECT * FROM memories WHERE memory_key = 'phase_4_revised_dod'"
    ).fetchone()
    assert seed is not None
    assert seed["active"] == 1
    assert seed["confidence"] == 1.0
    assert seed["sensitivity"] == "normal"
    assert seed["version"] == 1

    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_legacy_memory_table_is_upgraded_without_losing_data(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "legacy-structured-memory.db"

    db = _connect(database_path)
    db.executescript(
        """
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            memory_key TEXT NOT NULL UNIQUE,
            memory_value TEXT NOT NULL,
            importance INTEGER NOT NULL DEFAULT 5
                CHECK(importance BETWEEN 1 AND 10),
            source TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO memories
            (memory_type, memory_key, memory_value, importance, source, active,
             created_at, updated_at)
        VALUES
            ('technical_solution', 'legacy-memory-1',
             'Create indexes only after migrated columns exist.',
             10, 'phase_4_fix', 1,
             '2026-08-01 10:00:00', '2026-08-01 10:05:00');
        """
    )
    db.commit()
    db.close()

    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()
    database.init_db()

    db = _connect(database_path)
    _assert_memory_columns(db)

    memory = db.execute(
        "SELECT * FROM memories WHERE memory_key = 'legacy-memory-1'"
    ).fetchone()
    assert memory is not None
    assert memory["id"] == 1
    assert memory["memory_type"] == "technical_solution"
    assert memory["memory_value"] == (
        "Create indexes only after migrated columns exist."
    )
    assert memory["importance"] == 10
    assert memory["source"] == "phase_4_fix"
    assert memory["active"] == 1
    assert memory["created_at"] == "2026-08-01 10:00:00"
    assert memory["updated_at"] == "2026-08-01 10:05:00"

    assert memory["source_type"] is None
    assert memory["source_id"] is None
    assert memory["confidence"] == 1.0
    assert memory["sensitivity"] == "normal"
    assert memory["version"] == 1
    assert memory["superseded_by"] is None
    assert memory["last_used_at"] is None
    assert memory["content_hash"] is None

    assert db.execute(
        "SELECT COUNT(*) FROM memories WHERE memory_key = 'legacy-memory-1'"
    ).fetchone()[0] == 1

    for index_name, expected in EXPECTED_MEMORY_INDEXES.items():
        assert _index_details(db, "memories", index_name) == expected

    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()