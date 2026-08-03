import sqlite3

import pytest

from app import database


AGENT_RUN_COLUMNS = [
    "id",
    "session_id",
    "user_message_id",
    "request_key",
    "intent",
    "status",
    "loop_selected",
    "step_count",
    "ai_call_count",
    "tool_call_count",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "estimated_cost_microusd",
    "error_code",
    "error_message",
    "started_at",
    "completed_at",
    "created_at",
    "updated_at",
]

AGENT_STEP_COLUMNS = [
    "id",
    "run_id",
    "step_number",
    "step_key",
    "step_type",
    "name",
    "status",
    "tool_name",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "estimated_cost_microusd",
    "error_code",
    "error_message",
    "started_at",
    "completed_at",
    "created_at",
    "updated_at",
]

EXPECTED_AGENT_INDEXES = {
    "idx_agent_runs_session_created": (
        "agent_runs",
        False,
        ["session_id", "created_at", "id"],
    ),
    "idx_agent_runs_user_message_created": (
        "agent_runs",
        False,
        ["user_message_id", "created_at", "id"],
    ),
    "idx_agent_runs_status_updated": (
        "agent_runs",
        False,
        ["status", "updated_at", "id"],
    ),
    "idx_agent_runs_request_key": (
        "agent_runs",
        True,
        ["session_id", "request_key"],
    ),
    "idx_agent_steps_run_number": (
        "agent_steps",
        True,
        ["run_id", "step_number"],
    ),
    "idx_agent_steps_step_key": (
        "agent_steps",
        True,
        ["run_id", "step_key"],
    ),
}


def _connect(database_path) -> sqlite3.Connection:
    db = sqlite3.connect(database_path)
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _table_names(db: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _column_names(db: sqlite3.Connection, table_name: str) -> list[str]:
    return [row[1] for row in db.execute(f"PRAGMA table_info({table_name})")]


def _index_columns(db: sqlite3.Connection, index_name: str) -> list[str]:
    return [row[2] for row in db.execute(f"PRAGMA index_info({index_name})")]


def _index_details(
    db: sqlite3.Connection,
    table_name: str,
    index_name: str,
) -> tuple[bool, list[str]]:
    indexes = {
        row[1]: row
        for row in db.execute(f"PRAGMA index_list({table_name})").fetchall()
    }
    return bool(indexes[index_name][2]), _index_columns(db, index_name)


def _normalized_index_sql(db: sqlite3.Connection, index_name: str) -> str:
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index_name,),
    ).fetchone()
    assert row is not None and row[0] is not None
    return " ".join(row[0].lower().split()).rstrip(";")


def _create_static_step_5_1_chat_database(database_path) -> None:
    """Create the released Step 5.1 schema without running current migrations."""
    db = _connect(database_path)
    db.executescript(
        """
        CREATE TABLE chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'New chat',
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'archived')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_message_at TEXT,
            archived_at TEXT
        );

        CREATE TABLE chat_messages (
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

        CREATE INDEX idx_chat_sessions_status_activity
        ON chat_sessions(status, last_message_at DESC, updated_at DESC, id DESC);

        CREATE INDEX idx_chat_messages_recent
        ON chat_messages(session_id, deleted_at, created_at DESC, id DESC);

        CREATE UNIQUE INDEX idx_chat_messages_request_key
        ON chat_messages(session_id, request_key)
        WHERE request_key IS NOT NULL;

        INSERT INTO chat_sessions
            (id, title, status, created_at, updated_at, last_message_at, archived_at)
        VALUES
            (41, 'Persistent history', 'active', '2026-07-01 08:00:00',
             '2026-07-01 08:02:00', '2026-07-01 08:02:00', NULL),
            (42, 'Archived history', 'archived', '2026-06-01 09:00:00',
             '2026-06-02 09:00:00', '2026-06-01 09:01:00',
             '2026-06-02 09:00:00');

        INSERT INTO chat_messages
            (id, session_id, role, content, request_key, edited_at, deleted_at,
             created_at, updated_at)
        VALUES
            (71, 41, 'user', 'Keep this user message', 'request-71', NULL, NULL,
             '2026-07-01 08:01:00', '2026-07-01 08:01:00'),
            (72, 41, 'assistant', 'Keep this assistant message', 'request-72',
             NULL, NULL, '2026-07-01 08:02:00', '2026-07-01 08:02:00'),
            (73, 42, 'user', 'Keep this deleted message tombstone', NULL, NULL,
             '2026-06-02 09:00:00', '2026-06-01 09:01:00',
             '2026-06-02 09:00:00');
        """
    )
    db.commit()
    db.close()


def _chat_snapshot(db: sqlite3.Connection) -> dict[str, list[tuple]]:
    return {
        table_name: db.execute(
            f"SELECT * FROM {table_name} ORDER BY id"
        ).fetchall()
        for table_name in ("chat_sessions", "chat_messages")
    }


def _insert_chat_input(db: sqlite3.Connection) -> tuple[int, int]:
    session_id = db.execute(
        "INSERT INTO chat_sessions (title, status) VALUES ('Audit chat', 'active')"
    ).lastrowid
    message_id = db.execute(
        """
        INSERT INTO chat_messages (session_id, role, content, request_key)
        VALUES (?, 'user', 'Please audit this request', 'chat-request')
        """,
        (session_id,),
    ).lastrowid
    return session_id, message_id


def _insert_run(
    db: sqlite3.Connection,
    session_id: int,
    message_id: int,
    *,
    request_key: str | None = None,
) -> int:
    return db.execute(
        """
        INSERT INTO agent_runs (session_id, user_message_id, request_key)
        VALUES (?, ?, ?)
        """,
        (session_id, message_id, request_key),
    ).lastrowid


def _rewrite_temporary_table_schema(
    database_path,
    *,
    table_name: str,
    old_definition: str,
    new_definition: str,
) -> None:
    """Change one declared column definition in an isolated test database."""
    db = sqlite3.connect(database_path)
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    assert row is not None
    original_sql = row[0]
    assert original_sql.count(old_definition) == 1
    rewritten_sql = original_sql.replace(old_definition, new_definition, 1)

    # SQLite cannot add or remove these column constraints with ALTER TABLE.
    # writable_schema is safe here because the database is temporary, empty of
    # audit rows, and discarded by pytest after this compatibility check.
    db.execute("PRAGMA writable_schema = ON")
    db.execute(
        "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?",
        (rewritten_sql, table_name),
    )
    db.execute("PRAGMA writable_schema = OFF")
    db.commit()
    db.close()


def test_fresh_database_has_exact_agent_audit_schema_constraints_and_indexes(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "fresh-agent-audit.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    assert {"agent_runs", "agent_steps"}.issubset(_table_names(db))
    assert _column_names(db, "agent_runs") == AGENT_RUN_COLUMNS
    assert _column_names(db, "agent_steps") == AGENT_STEP_COLUMNS

    for index_name, (table_name, unique, columns) in EXPECTED_AGENT_INDEXES.items():
        assert _index_details(db, table_name, index_name) == (unique, columns)

    run_request_sql = _normalized_index_sql(db, "idx_agent_runs_request_key")
    _, separator, predicate = run_request_sql.partition(" where ")
    assert separator and predicate == "request_key is not null"

    step_key_sql = _normalized_index_sql(db, "idx_agent_steps_step_key")
    _, separator, predicate = step_key_sql.partition(" where ")
    assert separator and predicate == "step_key is not null"

    run_foreign_keys = db.execute("PRAGMA foreign_key_list(agent_runs)").fetchall()
    assert any(
        row[2] == "chat_sessions"
        and row[3] == "session_id"
        and row[4] == "id"
        and row[6] == "SET NULL"
        for row in run_foreign_keys
    )
    assert any(
        row[2] == "chat_messages"
        and row[3] == "user_message_id"
        and row[4] == "id"
        and row[6] == "SET NULL"
        for row in run_foreign_keys
    )
    step_foreign_keys = db.execute("PRAGMA foreign_key_list(agent_steps)").fetchall()
    assert any(
        row[2] == "agent_runs"
        and row[3] == "run_id"
        and row[4] == "id"
        and row[6] == "CASCADE"
        for row in step_foreign_keys
    )

    session_id, message_id = _insert_chat_input(db)
    run_id = _insert_run(db, session_id, message_id, request_key="agent-request")
    db.execute(
        """
        INSERT INTO agent_steps
            (run_id, step_number, step_key, step_type, name)
        VALUES (?, 1, 'classify', 'decision', 'classify_intent')
        """,
        (run_id,),
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO agent_runs (status) VALUES ('invalid')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO agent_runs (step_count) VALUES (-1)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO agent_runs (input_tokens) VALUES (-1)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO agent_runs (estimated_cost_microusd) VALUES (-1)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO agent_steps (run_id, step_number, step_type, name, status)
            VALUES (?, 2, 'validation', 'validate', 'invalid')
            """,
            (run_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO agent_steps (run_id, step_number, step_type, name)
            VALUES (?, 0, 'validation', 'validate')
            """,
            (run_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO agent_steps
                (run_id, step_number, step_type, name, output_tokens)
            VALUES (?, 2, 'ai_call', 'generate', -1)
            """,
            (run_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        _insert_run(db, session_id, message_id, request_key="agent-request")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO agent_steps (run_id, step_number, step_type, name)
            VALUES (?, 1, 'validation', 'duplicate_number')
            """,
            (run_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO agent_steps
                (run_id, step_number, step_key, step_type, name)
            VALUES (?, 2, 'classify', 'validation', 'duplicate_key')
            """,
            (run_id,),
        )

    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_agent_audit_foreign_key_delete_policies(tmp_path, monkeypatch):
    database_path = tmp_path / "agent-audit-delete-policies.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = _connect(database_path)
    session_id, message_id = _insert_chat_input(db)
    run_id = _insert_run(db, session_id, message_id)
    step_id = db.execute(
        """
        INSERT INTO agent_steps (run_id, step_number, step_type, name)
        VALUES (?, 1, 'validation', 'validate_request')
        """,
        (run_id,),
    ).lastrowid

    db.execute("DELETE FROM chat_messages WHERE id = ?", (message_id,))
    assert db.execute(
        "SELECT session_id, user_message_id FROM agent_runs WHERE id = ?",
        (run_id,),
    ).fetchone() == (session_id, None)

    db.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    assert db.execute(
        "SELECT session_id, user_message_id FROM agent_runs WHERE id = ?",
        (run_id,),
    ).fetchone() == (None, None)
    assert db.execute(
        "SELECT run_id FROM agent_steps WHERE id = ?", (step_id,)
    ).fetchone() == (run_id,)

    db.execute("DELETE FROM agent_runs WHERE id = ?", (run_id,))
    assert db.execute(
        "SELECT 1 FROM agent_steps WHERE id = ?", (step_id,)
    ).fetchone() is None
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_static_step_5_1_chat_data_is_unchanged_by_agent_audit_migration(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "step-5-1.db"
    _create_static_step_5_1_chat_database(database_path)
    monkeypatch.setattr(database, "DB_PATH", database_path)

    before_db = _connect(database_path)
    before = _chat_snapshot(before_db)
    before_db.close()

    database.init_db()
    database.init_db()

    after_db = _connect(database_path)
    assert _chat_snapshot(after_db) == before
    assert {"agent_runs", "agent_steps"}.issubset(_table_names(after_db))
    assert after_db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0
    assert after_db.execute("SELECT COUNT(*) FROM agent_steps").fetchone()[0] == 0
    assert after_db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert after_db.execute("PRAGMA foreign_key_check").fetchall() == []
    after_db.close()


def test_existing_agent_audit_rows_survive_repeated_startup(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "existing-agent-audit.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = _connect(database_path)
    session_id, message_id = _insert_chat_input(db)
    run_id = db.execute(
        """
        INSERT INTO agent_runs
            (session_id, user_message_id, request_key, intent, status,
             loop_selected, step_count, ai_call_count, provider, model,
             input_tokens, output_tokens, estimated_cost_microusd,
             started_at, completed_at, created_at, updated_at)
        VALUES
            (?, ?, 'existing-run', 'chat', 'completed', 'chat_loop',
             1, 1, 'test-provider', 'test-model', 12, 4, 25,
             '2026-08-01 10:00:00', '2026-08-01 10:00:01',
             '2026-08-01 10:00:00', '2026-08-01 10:00:01')
        """,
        (session_id, message_id),
    ).lastrowid
    db.execute(
        """
        INSERT INTO agent_steps
            (run_id, step_number, step_key, step_type, name, status,
             provider, model, input_tokens, output_tokens,
             estimated_cost_microusd, started_at, completed_at,
             created_at, updated_at)
        VALUES
            (?, 1, 'existing-step', 'ai_call', 'generate_response',
             'completed', 'test-provider', 'test-model', 12, 4, 25,
             '2026-08-01 10:00:00', '2026-08-01 10:00:01',
             '2026-08-01 10:00:00', '2026-08-01 10:00:01')
        """,
        (run_id,),
    )
    db.commit()
    before_runs = db.execute("SELECT * FROM agent_runs ORDER BY id").fetchall()
    before_steps = db.execute("SELECT * FROM agent_steps ORDER BY id").fetchall()
    db.close()

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    assert db.execute("SELECT * FROM agent_runs ORDER BY id").fetchall() == before_runs
    assert db.execute("SELECT * FROM agent_steps ORDER BY id").fetchall() == before_steps
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_incompatible_partial_agent_audit_schema_fails_without_data_loss(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "partial-agent-audit.db"
    db = _connect(database_path)
    db.executescript(
        """
        CREATE TABLE agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intent TEXT
        );
        CREATE TABLE agent_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER
        );
        INSERT INTO agent_runs (id, intent) VALUES (17, 'preserve-me');
        INSERT INTO agent_steps (id, run_id) VALUES (29, 17);
        """
    )
    db.commit()
    db.close()
    monkeypatch.setattr(database, "DB_PATH", database_path)

    with pytest.raises(RuntimeError, match="agent_runs"):
        database.init_db()

    db = _connect(database_path)
    assert db.execute("SELECT * FROM agent_runs WHERE id = 17").fetchone() == (
        17,
        "preserve-me",
    )
    assert db.execute("SELECT * FROM agent_steps WHERE id = 29").fetchone() == (
        29,
        17,
    )
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


def test_agent_run_optional_column_made_required_fails_validation(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "required-run-provider.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()
    _rewrite_temporary_table_schema(
        database_path,
        table_name="agent_runs",
        old_definition="provider TEXT,",
        new_definition="provider TEXT NOT NULL,",
    )

    with pytest.raises(RuntimeError, match=r"must be nullable: provider"):
        database.init_db()

    db = sqlite3.connect(database_path)
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


def test_agent_step_optional_column_made_required_fails_validation(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "required-step-tool-name.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()
    _rewrite_temporary_table_schema(
        database_path,
        table_name="agent_steps",
        old_definition="tool_name TEXT,",
        new_definition="tool_name TEXT NOT NULL,",
    )

    with pytest.raises(RuntimeError, match=r"must be nullable: tool_name"):
        database.init_db()

    db = sqlite3.connect(database_path)
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


def test_agent_run_missing_aggregate_default_fails_validation(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "missing-run-step-count-default.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()
    _rewrite_temporary_table_schema(
        database_path,
        table_name="agent_runs",
        old_definition=(
            "step_count INTEGER NOT NULL DEFAULT 0 CHECK(step_count >= 0)"
        ),
        new_definition="step_count INTEGER NOT NULL CHECK(step_count >= 0)",
    )

    with pytest.raises(RuntimeError, match=r"incorrect defaults: step_count"):
        database.init_db()

    db = sqlite3.connect(database_path)
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


@pytest.mark.parametrize("orphan_kind", ["run", "step"])
def test_orphaned_agent_audit_reference_fails_without_data_loss(
    tmp_path,
    monkeypatch,
    orphan_kind,
):
    database_path = tmp_path / f"orphan-{orphan_kind}.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = sqlite3.connect(database_path)
    db.execute("PRAGMA foreign_keys = OFF")
    if orphan_kind == "run":
        orphan_id = db.execute(
            """
            INSERT INTO agent_runs (session_id, user_message_id)
            VALUES (9998, 9999)
            """
        ).lastrowid
        table_name = "agent_runs"
    else:
        orphan_id = db.execute(
            """
            INSERT INTO agent_steps (run_id, step_number, step_type, name)
            VALUES (9999, 1, 'validation', 'orphan_step')
            """
        ).lastrowid
        table_name = "agent_steps"
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="orphan"):
        database.init_db()

    db = sqlite3.connect(database_path)
    assert db.execute(
        f"SELECT id FROM {table_name} WHERE id = ?", (orphan_id,)
    ).fetchone() == (orphan_id,)
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


@pytest.mark.parametrize(
    ("index_name", "replacement_sql"),
    [
        (
            "idx_agent_runs_status_updated",
            """
            CREATE INDEX idx_agent_runs_status_updated
            ON agent_runs(status, created_at, id)
            """,
        ),
        (
            "idx_agent_runs_request_key",
            """
            CREATE UNIQUE INDEX idx_agent_runs_request_key
            ON agent_runs(session_id, request_key)
            WHERE request_key IS NOT NULL AND status = 'running'
            """,
        ),
        (
            "idx_agent_steps_step_key",
            """
            CREATE UNIQUE INDEX idx_agent_steps_step_key
            ON agent_steps(run_id, step_key)
            WHERE step_key IS NOT NULL AND status = 'completed'
            """,
        ),
        (
            "idx_agent_steps_run_number",
            """
            CREATE UNIQUE INDEX idx_agent_steps_run_number
            ON agent_steps(run_id, step_number)
            WHERE status = 'completed'
            """,
        ),
    ],
)
def test_wrong_existing_agent_audit_index_fails_validation(
    tmp_path,
    monkeypatch,
    index_name,
    replacement_sql,
):
    database_path = tmp_path / f"wrong-{index_name}.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = _connect(database_path)
    db.execute(f"DROP INDEX {index_name}")
    db.execute(replacement_sql)
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="index"):
        database.init_db()

    db = _connect(database_path)
    assert index_name in {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()
