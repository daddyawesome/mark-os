from __future__ import annotations

import sqlite3


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'New chat',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_message_at TEXT,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role TEXT NOT NULL
        CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    request_key TEXT,
    edited_at TEXT,
    deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);
"""


INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_chat_sessions_status_activity
ON chat_sessions(status, last_message_at DESC, updated_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_recent
ON chat_messages(session_id, deleted_at, created_at DESC, id DESC);
"""


def validate_schema(db: sqlite3.Connection) -> None:
    """Fail safely instead of accepting a weakened experimental chat schema."""
    required_columns = {
        "chat_sessions": {
            "id",
            "title",
            "status",
            "created_at",
            "updated_at",
            "last_message_at",
            "archived_at",
        },
        "chat_messages": {
            "id",
            "session_id",
            "role",
            "content",
            "request_key",
            "edited_at",
            "deleted_at",
            "created_at",
            "updated_at",
        },
    }
    required_not_null = {
        "chat_sessions": {"title", "status", "created_at", "updated_at"},
        "chat_messages": {"session_id", "role", "content", "created_at", "updated_at"},
    }

    for table_name, expected_columns in required_columns.items():
        table_info = db.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = {row["name"]: row for row in table_info}
        missing = expected_columns - set(columns)
        if missing:
            missing_names = ", ".join(sorted(missing))
            raise RuntimeError(
                f"Incompatible {table_name} schema; missing columns: {missing_names}"
            )
        nullable = {
            name
            for name in required_not_null[table_name]
            if not columns[name]["notnull"]
        }
        if nullable:
            nullable_names = ", ".join(sorted(nullable))
            raise RuntimeError(
                f"Incompatible {table_name} schema; required columns are nullable: "
                f"{nullable_names}"
            )
        id_column = columns["id"]
        if id_column["type"].upper() != "INTEGER" or id_column["pk"] != 1:
            raise RuntimeError(
                f"Incompatible {table_name} schema; id must be INTEGER PRIMARY KEY"
            )

    message_columns = {
        row["name"]: row
        for row in db.execute("PRAGMA table_info(chat_messages)").fetchall()
    }
    if message_columns["session_id"]["type"].upper() != "INTEGER":
        raise RuntimeError(
            "Incompatible chat_messages schema; session_id must be INTEGER"
        )

    session_sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'chat_sessions'"
    ).fetchone()["sql"]
    message_sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'chat_messages'"
    ).fetchone()["sql"]
    normalized_session_sql = " ".join(session_sql.lower().split())
    normalized_message_sql = " ".join(message_sql.lower().split())
    if "check(status in ('active', 'archived'))" not in normalized_session_sql:
        raise RuntimeError("Incompatible chat_sessions schema; status constraint is missing")
    if (
        "check(role in ('user', 'assistant', 'system', 'tool'))"
        not in normalized_message_sql
    ):
        raise RuntimeError("Incompatible chat_messages schema; role constraint is missing")

    foreign_keys = db.execute("PRAGMA foreign_key_list(chat_messages)").fetchall()
    has_session_cascade = any(
        row["table"] == "chat_sessions"
        and row["from"] == "session_id"
        and row["to"] == "id"
        and row["on_delete"].upper() == "CASCADE"
        for row in foreign_keys
    )
    if not has_session_cascade:
        raise RuntimeError(
            "Incompatible chat_messages schema; session cascade foreign key is missing"
        )

    foreign_key_violations = db.execute(
        "PRAGMA foreign_key_check(chat_messages)"
    ).fetchall()
    if foreign_key_violations:
        raise RuntimeError(
            "Incompatible chat_messages data; orphaned session references exist"
        )


def create_unique_indexes(db: sqlite3.Connection) -> None:
    # A request key identifies one network/form submission within a session.
    # Identical content remains valid when it has a different request key.
    try:
        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_request_key
            ON chat_messages(session_id, request_key)
            WHERE request_key IS NOT NULL
            """
        )
    except sqlite3.IntegrityError as exc:
        raise RuntimeError(
            "Cannot enable chat duplicate protection because duplicate request keys "
            "already exist"
        ) from exc


def validate_indexes(db: sqlite3.Connection) -> None:
    expected = {
        "idx_chat_sessions_status_activity": (
            "chat_sessions",
            False,
            ["status", "last_message_at", "updated_at", "id"],
        ),
        "idx_chat_messages_recent": (
            "chat_messages",
            False,
            ["session_id", "deleted_at", "created_at", "id"],
        ),
        "idx_chat_messages_request_key": (
            "chat_messages",
            True,
            ["session_id", "request_key"],
        ),
    }

    for index_name, (table_name, must_be_unique, expected_columns) in expected.items():
        index_rows = {
            row["name"]: row
            for row in db.execute(f"PRAGMA index_list({table_name})").fetchall()
        }
        index = index_rows.get(index_name)
        columns = [
            row["name"]
            for row in db.execute(f"PRAGMA index_info({index_name})").fetchall()
        ]
        if (
            index is None
            or bool(index["unique"]) is not must_be_unique
            or columns != expected_columns
        ):
            raise RuntimeError(f"Incompatible chat index: {index_name}")

    request_index = db.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type = 'index' AND name = 'idx_chat_messages_request_key'
        """
    ).fetchone()
    normalized_index_sql = " ".join(request_index["sql"].lower().split()).rstrip(";")
    _, separator, predicate = normalized_index_sql.partition(" where ")
    if not separator or predicate.strip() != "request_key is not null":
        raise RuntimeError(
            "Incompatible chat index: idx_chat_messages_request_key has the wrong predicate"
        )
