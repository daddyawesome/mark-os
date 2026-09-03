from __future__ import annotations

import sqlite3

from app.db.schema import column_names, ensure_column, table_exists


MEMORY_ACTIVE_KEY_INDEX = "ux_memories_user_key"
MEMORY_VERSION_INDEX = "ux_memories_user_key_version"
MEMORY_CANDIDATE_REQUEST_INDEX = "ux_memory_candidates_user_request"
MEMORY_CANDIDATE_PENDING_HASH_INDEX = "ux_memory_candidates_pending_hash"

TRIGGER_NAMES = (
    "trg_memories_owner_immutable",
    "trg_memories_supersession_insert",
    "trg_memories_supersession_update",
    "trg_memories_supersession_delete_guard",
    "trg_memory_candidates_owner_immutable",
    "trg_memory_candidates_references_insert",
    "trg_memory_candidates_references_update",
    "trg_memory_audit_references_insert",
    "trg_memory_audit_no_update",
    "trg_memory_audit_no_delete",
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_type TEXT NOT NULL,
    memory_key TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS memory_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    memory_type TEXT NOT NULL CHECK(length(trim(memory_type)) > 0),
    memory_key TEXT NOT NULL CHECK(length(trim(memory_key)) > 0),
    memory_value TEXT NOT NULL CHECK(length(trim(memory_value)) > 0),
    importance INTEGER NOT NULL DEFAULT 5
        CHECK(importance BETWEEN 1 AND 10),
    source TEXT NOT NULL CHECK(length(trim(source)) > 0),
    source_type TEXT,
    source_id INTEGER,
    agent_run_id INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0
        CHECK(confidence BETWEEN 0.0 AND 1.0),
    sensitivity TEXT NOT NULL DEFAULT 'normal'
        CHECK(sensitivity IN ('normal', 'private', 'restricted')),
    candidate_reason TEXT NOT NULL
        CHECK(length(trim(candidate_reason)) > 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'accepted', 'rejected', 'archived')),
    content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
    request_key TEXT,
    accepted_memory_id INTEGER,
    resolution_reason TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(source_id IS NULL OR length(trim(source_type)) > 0),
    CHECK(request_key IS NULL OR length(trim(request_key)) > 0),
    CHECK(
        (status = 'pending'
            AND resolved_at IS NULL
            AND accepted_memory_id IS NULL
            AND resolution_reason IS NULL)
        OR (status = 'accepted'
            AND resolved_at IS NOT NULL
            AND accepted_memory_id IS NOT NULL
            AND resolution_reason IS NULL)
        OR (status IN ('rejected', 'archived')
            AND resolved_at IS NOT NULL
            AND accepted_memory_id IS NULL)
    ),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL,
    FOREIGN KEY(accepted_memory_id) REFERENCES memories(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS memory_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK(length(trim(event_type)) > 0),
    actor_user_id INTEGER,
    memory_id INTEGER,
    candidate_id INTEGER,
    agent_run_id INTEGER,
    source TEXT NOT NULL CHECK(length(trim(source)) > 0),
    details_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE SET NULL,
    FOREIGN KEY(candidate_id) REFERENCES memory_candidates(id) ON DELETE SET NULL,
    FOREIGN KEY(agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
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

CREATE INDEX IF NOT EXISTS idx_memory_candidates_user_status
ON memory_candidates(user_id, status, importance DESC, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_source
ON memory_candidates(user_id, source_type, source_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_audit_user_time
ON memory_audit_events(user_id, occurred_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_audit_memory
ON memory_audit_events(user_id, memory_id, occurred_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_audit_candidate
ON memory_audit_events(user_id, candidate_id, occurred_at DESC, id DESC);
"""


TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_memories_owner_immutable
BEFORE UPDATE OF user_id ON memories
WHEN OLD.user_id IS NOT NEW.user_id
BEGIN
    SELECT RAISE(ABORT, 'memory owner is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_memories_supersession_insert
BEFORE INSERT ON memories
WHEN NEW.superseded_by IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM memories AS newer
    WHERE newer.id = NEW.superseded_by
      AND newer.user_id = NEW.user_id
      AND newer.memory_key = NEW.memory_key
      AND newer.version > NEW.version
 )
BEGIN
    SELECT RAISE(ABORT, 'memory supersession target is invalid');
END;

CREATE TRIGGER IF NOT EXISTS trg_memories_supersession_update
BEFORE UPDATE OF user_id, memory_key, version, active, superseded_by ON memories
WHEN NEW.superseded_by IS NOT NULL
 AND (
    NEW.active != 0
    OR NOT EXISTS (
        SELECT 1
        FROM memories AS newer
        WHERE newer.id = NEW.superseded_by
          AND newer.user_id = NEW.user_id
          AND newer.memory_key = NEW.memory_key
          AND newer.version > NEW.version
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'memory supersession target is invalid');
END;

CREATE TRIGGER IF NOT EXISTS trg_memories_supersession_delete_guard
BEFORE DELETE ON memories
WHEN EXISTS (
    SELECT 1 FROM memories AS older WHERE older.superseded_by = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'referenced memory version cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_candidates_owner_immutable
BEFORE UPDATE OF user_id ON memory_candidates
WHEN OLD.user_id IS NOT NEW.user_id
BEGIN
    SELECT RAISE(ABORT, 'memory candidate owner is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_candidates_references_insert
BEFORE INSERT ON memory_candidates
WHEN (
    NEW.agent_run_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM agent_runs
        WHERE id = NEW.agent_run_id AND user_id = NEW.user_id
    )
 ) OR (
    NEW.accepted_memory_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM memories
        WHERE id = NEW.accepted_memory_id AND user_id = NEW.user_id
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'memory candidate reference owner mismatch');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_candidates_references_update
BEFORE UPDATE OF user_id, agent_run_id, accepted_memory_id ON memory_candidates
WHEN (
    NEW.agent_run_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM agent_runs
        WHERE id = NEW.agent_run_id AND user_id = NEW.user_id
    )
 ) OR (
    NEW.accepted_memory_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM memories
        WHERE id = NEW.accepted_memory_id AND user_id = NEW.user_id
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'memory candidate reference owner mismatch');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_audit_references_insert
BEFORE INSERT ON memory_audit_events
WHEN (
    NEW.memory_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM memories
        WHERE id = NEW.memory_id AND user_id = NEW.user_id
    )
 ) OR (
    NEW.candidate_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM memory_candidates
        WHERE id = NEW.candidate_id AND user_id = NEW.user_id
    )
 ) OR (
    NEW.agent_run_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM agent_runs
        WHERE id = NEW.agent_run_id AND user_id = NEW.user_id
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'memory audit reference owner mismatch');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_audit_no_update
BEFORE UPDATE ON memory_audit_events
BEGIN
    SELECT RAISE(ABORT, 'memory audit events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_audit_no_delete
BEFORE DELETE ON memory_audit_events
BEGIN
    SELECT RAISE(ABORT, 'memory audit events are append-only');
END;
"""


def migrate(db: sqlite3.Connection) -> None:
    """Add structured-memory fields without replacing existing data."""
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


def _index_columns(db: sqlite3.Connection, index_name: str) -> list[str]:
    return [
        str(row["name"])
        for row in db.execute(f"PRAGMA index_info({index_name})").fetchall()
    ]


def _normalized_index_sql(
    db: sqlite3.Connection,
    index_name: str,
) -> str | None:
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index_name,),
    ).fetchone()
    if row is None or row["sql"] is None:
        return None
    return " ".join(str(row["sql"]).lower().split()).rstrip(";")


def create_unique_indexes(db: sqlite3.Connection) -> None:
    """Enable version history while keeping one active key per user."""
    if "user_id" not in column_names(db, "memories"):
        return

    active_index_sql = _normalized_index_sql(db, MEMORY_ACTIVE_KEY_INDEX)
    active_index_is_current = (
        active_index_sql is not None
        and _index_columns(db, MEMORY_ACTIVE_KEY_INDEX)
        == ["user_id", "memory_key"]
        and " where active = 1" in active_index_sql
    )

    try:
        if not active_index_is_current:
            db.execute(f"DROP INDEX IF EXISTS {MEMORY_ACTIVE_KEY_INDEX}")
            db.execute(
                f"""
                CREATE UNIQUE INDEX {MEMORY_ACTIVE_KEY_INDEX}
                ON memories(user_id, memory_key)
                WHERE active = 1
                """
            )

        db.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {MEMORY_VERSION_INDEX}
            ON memories(user_id, memory_key, version)
            """
        )
        db.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {MEMORY_CANDIDATE_REQUEST_INDEX}
            ON memory_candidates(user_id, request_key)
            WHERE request_key IS NOT NULL
            """
        )
        db.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {MEMORY_CANDIDATE_PENDING_HASH_INDEX}
            ON memory_candidates(user_id, content_hash)
            WHERE status = 'pending'
            """
        )
    except sqlite3.IntegrityError as exc:
        raise RuntimeError(
            "Cannot enable Phase 8.1 memory idempotency because duplicate "
            "active keys, versions, request keys, or pending candidates exist"
        ) from exc


def drop_triggers(db: sqlite3.Connection) -> None:
    for trigger_name in TRIGGER_NAMES:
        db.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")


def create_triggers(db: sqlite3.Connection) -> None:
    db.executescript(TRIGGER_SQL)


def validate_schema(db: sqlite3.Connection) -> None:
    required_columns = {
        "memories": {
            "id",
            "user_id",
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
        },
        "memory_candidates": {
            "id",
            "user_id",
            "memory_type",
            "memory_key",
            "memory_value",
            "importance",
            "source",
            "source_type",
            "source_id",
            "agent_run_id",
            "confidence",
            "sensitivity",
            "candidate_reason",
            "status",
            "content_hash",
            "request_key",
            "accepted_memory_id",
            "resolution_reason",
            "resolved_at",
            "created_at",
            "updated_at",
        },
        "memory_audit_events": {
            "id",
            "user_id",
            "event_type",
            "actor_user_id",
            "memory_id",
            "candidate_id",
            "agent_run_id",
            "source",
            "details_json",
            "occurred_at",
        },
    }
    required_not_null = {
        "memory_candidates": {
            "user_id",
            "memory_type",
            "memory_key",
            "memory_value",
            "importance",
            "source",
            "confidence",
            "sensitivity",
            "candidate_reason",
            "status",
            "content_hash",
            "created_at",
            "updated_at",
        },
        "memory_audit_events": {
            "user_id",
            "event_type",
            "source",
            "details_json",
            "occurred_at",
        },
    }

    for table_name, expected_columns in required_columns.items():
        if not table_exists(db, table_name):
            raise RuntimeError(f"Phase 8.1 memory table is missing: {table_name}")
        columns = {
            str(row["name"]): row
            for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        missing = expected_columns - set(columns)
        if missing:
            raise RuntimeError(
                f"Incompatible {table_name} schema; missing columns: "
                + ", ".join(sorted(missing))
            )
        nullable = {
            name
            for name in required_not_null.get(table_name, set())
            if not columns[name]["notnull"]
        }
        if nullable:
            raise RuntimeError(
                f"Incompatible {table_name} schema; required columns are nullable: "
                + ", ".join(sorted(nullable))
            )

    candidate_row = db.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type = 'table' AND name = 'memory_candidates'
        """
    ).fetchone()
    candidate_sql = " ".join(str(candidate_row["sql"]).lower().split())
    required_candidate_checks = (
        "check(importance between 1 and 10)",
        "check(confidence between 0.0 and 1.0)",
        "check(sensitivity in ('normal', 'private', 'restricted'))",
        "check(status in ('pending', 'accepted', 'rejected', 'archived'))",
        "check(length(content_hash) = 64)",
        "status = 'pending'",
        "status = 'accepted'",
        "status in ('rejected', 'archived')",
    )
    if any(fragment not in candidate_sql for fragment in required_candidate_checks):
        raise RuntimeError(
            "Incompatible memory_candidates schema; required constraints are missing"
        )

    candidate_foreign_keys = {
        (row["table"], row["from"], row["to"], row["on_delete"].upper())
        for row in db.execute("PRAGMA foreign_key_list(memory_candidates)")
    }
    if candidate_foreign_keys != {
        ("users", "user_id", "id", "CASCADE"),
        ("agent_runs", "agent_run_id", "id", "SET NULL"),
        ("memories", "accepted_memory_id", "id", "SET NULL"),
    }:
        raise RuntimeError("Incompatible memory_candidates foreign keys")

    audit_foreign_keys = {
        (row["table"], row["from"], row["to"], row["on_delete"].upper())
        for row in db.execute("PRAGMA foreign_key_list(memory_audit_events)")
    }
    if audit_foreign_keys != {
        ("users", "user_id", "id", "CASCADE"),
        ("users", "actor_user_id", "id", "SET NULL"),
        ("memories", "memory_id", "id", "SET NULL"),
        ("memory_candidates", "candidate_id", "id", "SET NULL"),
        ("agent_runs", "agent_run_id", "id", "SET NULL"),
    }:
        raise RuntimeError("Incompatible memory_audit_events foreign keys")

    invalid_supersession = db.execute(
        """
        SELECT older.id
        FROM memories AS older
        LEFT JOIN memories AS newer ON newer.id = older.superseded_by
        WHERE older.superseded_by IS NOT NULL
          AND (
            older.active != 0
            OR newer.id IS NULL
            OR newer.user_id != older.user_id
            OR newer.memory_key != older.memory_key
            OR newer.version <= older.version
          )
        LIMIT 1
        """
    ).fetchone()
    if invalid_supersession is not None:
        raise RuntimeError("Invalid structured-memory supersession chain")

    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Foreign-key violations remain in structured memory")


def validate_indexes(db: sqlite3.Connection) -> None:
    expected = {
        MEMORY_ACTIVE_KEY_INDEX: (
            "memories",
            True,
            ["user_id", "memory_key"],
            "active = 1",
        ),
        MEMORY_VERSION_INDEX: (
            "memories",
            True,
            ["user_id", "memory_key", "version"],
            None,
        ),
        MEMORY_CANDIDATE_REQUEST_INDEX: (
            "memory_candidates",
            True,
            ["user_id", "request_key"],
            "request_key is not null",
        ),
        MEMORY_CANDIDATE_PENDING_HASH_INDEX: (
            "memory_candidates",
            True,
            ["user_id", "content_hash"],
            "status = 'pending'",
        ),
        "idx_memory_candidates_user_status": (
            "memory_candidates",
            False,
            ["user_id", "status", "importance", "created_at", "id"],
            None,
        ),
        "idx_memory_candidates_source": (
            "memory_candidates",
            False,
            ["user_id", "source_type", "source_id", "created_at", "id"],
            None,
        ),
        "idx_memory_audit_user_time": (
            "memory_audit_events",
            False,
            ["user_id", "occurred_at", "id"],
            None,
        ),
        "idx_memory_audit_memory": (
            "memory_audit_events",
            False,
            ["user_id", "memory_id", "occurred_at", "id"],
            None,
        ),
        "idx_memory_audit_candidate": (
            "memory_audit_events",
            False,
            ["user_id", "candidate_id", "occurred_at", "id"],
            None,
        ),
    }

    for index_name, (table_name, unique, columns, predicate) in expected.items():
        indexes = {
            str(row["name"]): row
            for row in db.execute(f"PRAGMA index_list({table_name})").fetchall()
        }
        index = indexes.get(index_name)
        if (
            index is None
            or bool(index["unique"]) is not unique
            or _index_columns(db, index_name) != columns
        ):
            raise RuntimeError(f"Incompatible structured-memory index: {index_name}")
        sql = _normalized_index_sql(db, index_name)
        if predicate is None:
            if bool(index["partial"]):
                raise RuntimeError(
                    f"Incompatible structured-memory index: {index_name}"
                )
        elif (
            not bool(index["partial"])
            or sql is None
            or sql.partition(" where ")[2].strip() != predicate
        ):
            raise RuntimeError(f"Incompatible structured-memory index: {index_name}")


def validate_triggers(db: sqlite3.Connection) -> None:
    found = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    missing = set(TRIGGER_NAMES) - found
    if missing:
        raise RuntimeError(
            "Missing structured-memory triggers: " + ", ".join(sorted(missing))
        )


def seed(db: sqlite3.Connection) -> None:
    owner = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner'
        ORDER BY active DESC, id
        LIMIT 1
        """
    ).fetchone()
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(memories)").fetchall()
    }
    memory_value = (
        "A quest can be created, opened, started, blocked, updated, and completed. "
        "Updates preserve progress, notes, minutes, and timestamp history. "
        "Completion requires a result, records evidence and actual time, creates a "
        "timeline event, and awards immutable XP exactly once in a transaction. "
        "Hidden threshold crossing records level-up history."
    )
    memory_key = "phase_4_revised_dod"

    if owner is not None and "user_id" in columns:
        owner_id = int(owner["id"])
        db.execute(
            """
            INSERT INTO memories
                (user_id, memory_type, memory_key, memory_value,
                 importance, source)
            SELECT ?, 'product_principle', ?, ?, 9, 'phase_4_revised'
            WHERE NOT EXISTS (
                SELECT 1
                FROM memories
                WHERE user_id = ? AND memory_key = ?
            )
            """,
            (owner_id, memory_key, memory_value, owner_id, memory_key),
        )
    else:
        db.execute(
            """
            INSERT INTO memories
                (memory_type, memory_key, memory_value, importance, source)
            SELECT 'product_principle', ?, ?, 9, 'phase_4_revised'
            WHERE NOT EXISTS (
                SELECT 1 FROM memories WHERE memory_key = ?
            )
            """,
            (memory_key, memory_value, memory_key),
        )
