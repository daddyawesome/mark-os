from __future__ import annotations

import sqlite3


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    user_message_id INTEGER,
    request_key TEXT,
    intent TEXT NOT NULL DEFAULT 'unknown'
        CHECK(length(trim(intent)) > 0),
    status TEXT NOT NULL DEFAULT 'running'
        CHECK(status IN ('running', 'completed', 'failed', 'cancelled')),
    loop_selected TEXT NOT NULL DEFAULT 'none'
        CHECK(length(trim(loop_selected)) > 0),
    step_count INTEGER NOT NULL DEFAULT 0 CHECK(step_count >= 0),
    ai_call_count INTEGER NOT NULL DEFAULT 0 CHECK(ai_call_count >= 0),
    tool_call_count INTEGER NOT NULL DEFAULT 0 CHECK(tool_call_count >= 0),
    provider TEXT,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
    estimated_cost_microusd INTEGER NOT NULL DEFAULT 0
        CHECK(estimated_cost_microusd >= 0),
    error_code TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (status = 'running' AND completed_at IS NULL)
        OR (
            status IN ('completed', 'failed', 'cancelled')
            AND completed_at IS NOT NULL
        )
    ),
    FOREIGN KEY (session_id)
        REFERENCES chat_sessions(id) ON DELETE SET NULL,
    FOREIGN KEY (user_message_id)
        REFERENCES chat_messages(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS agent_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    step_number INTEGER NOT NULL CHECK(step_number >= 1),
    step_key TEXT,
    step_type TEXT NOT NULL CHECK(length(trim(step_type)) > 0),
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    status TEXT NOT NULL DEFAULT 'running'
        CHECK(status IN (
            'running', 'completed', 'failed', 'cancelled', 'skipped'
        )),
    tool_name TEXT,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
    estimated_cost_microusd INTEGER NOT NULL DEFAULT 0
        CHECK(estimated_cost_microusd >= 0),
    error_code TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (status = 'running' AND completed_at IS NULL)
        OR (
            status IN ('completed', 'failed', 'cancelled', 'skipped')
            AND completed_at IS NOT NULL
        )
    ),
    FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
);
"""


INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_agent_runs_session_created
ON agent_runs(session_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_message_created
ON agent_runs(user_message_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runs_status_updated
ON agent_runs(status, updated_at DESC, id DESC);
"""


def validate_schema(db: sqlite3.Connection) -> None:
    """Reject weakened or partial agent-audit tables without rewriting them."""
    required_columns = {
        "agent_runs": {
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
        },
        "agent_steps": {
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
        },
    }
    required_not_null = {
        "agent_runs": {
            "intent",
            "status",
            "loop_selected",
            "step_count",
            "ai_call_count",
            "tool_call_count",
            "input_tokens",
            "output_tokens",
            "estimated_cost_microusd",
            "started_at",
            "created_at",
            "updated_at",
        },
        "agent_steps": {
            "run_id",
            "step_number",
            "step_type",
            "name",
            "status",
            "input_tokens",
            "output_tokens",
            "estimated_cost_microusd",
            "started_at",
            "created_at",
            "updated_at",
        },
    }
    integer_columns = {
        "agent_runs": {
            "id",
            "session_id",
            "user_message_id",
            "step_count",
            "ai_call_count",
            "tool_call_count",
            "input_tokens",
            "output_tokens",
            "estimated_cost_microusd",
        },
        "agent_steps": {
            "id",
            "run_id",
            "step_number",
            "input_tokens",
            "output_tokens",
            "estimated_cost_microusd",
        },
    }
    required_defaults = {
        "agent_runs": {
            "step_count": "0",
            "ai_call_count": "0",
            "tool_call_count": "0",
            "input_tokens": "0",
            "output_tokens": "0",
            "estimated_cost_microusd": "0",
        },
        "agent_steps": {},
    }

    table_sql: dict[str, str] = {}
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

        must_remain_nullable = {
            "agent_runs": {
                "session_id",
                "user_message_id",
                "request_key",
                "provider",
                "model",
                "error_code",
                "error_message",
                "completed_at",
            },
            "agent_steps": {
                "step_key",
                "tool_name",
                "provider",
                "model",
                "error_code",
                "error_message",
                "completed_at",
            },
        }
        incorrectly_required = {
            name
            for name in must_remain_nullable[table_name]
            if columns[name]["notnull"]
        }
        if incorrectly_required:
            required_names = ", ".join(sorted(incorrectly_required))
            raise RuntimeError(
                f"Incompatible {table_name} schema; columns must be nullable: "
                f"{required_names}"
            )

        wrong_defaults = {
            name
            for name, expected_default in required_defaults[table_name].items()
            if columns[name]["dflt_value"] != expected_default
        }
        if wrong_defaults:
            default_names = ", ".join(sorted(wrong_defaults))
            raise RuntimeError(
                f"Incompatible {table_name} schema; columns have incorrect defaults: "
                f"{default_names}"
            )

        wrong_types = {
            name
            for name in integer_columns[table_name]
            if columns[name]["type"].upper() != "INTEGER"
        }
        if wrong_types:
            type_names = ", ".join(sorted(wrong_types))
            raise RuntimeError(
                f"Incompatible {table_name} schema; columns must be INTEGER: "
                f"{type_names}"
            )

        id_column = columns["id"]
        if id_column["pk"] != 1:
            raise RuntimeError(
                f"Incompatible {table_name} schema; id must be INTEGER PRIMARY KEY"
            )

        table_row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        normalized_sql = " ".join(table_row["sql"].lower().split())
        table_sql[table_name] = normalized_sql.replace("( ", "(").replace(
            " )", ")"
        )

    run_sql = table_sql["agent_runs"]
    step_sql = table_sql["agent_steps"]
    required_run_checks = (
        "check(status in ('running', 'completed', 'failed', 'cancelled'))",
        "check(step_count >= 0)",
        "check(ai_call_count >= 0)",
        "check(tool_call_count >= 0)",
        "check(input_tokens >= 0)",
        "check(output_tokens >= 0)",
        "check(estimated_cost_microusd >= 0)",
        "status = 'running' and completed_at is null",
        "status in ('completed', 'failed', 'cancelled') and completed_at is not null",
    )
    required_step_checks = (
        "check(step_number >= 1)",
        "check(status in ('running', 'completed', 'failed', 'cancelled', 'skipped'))",
        "check(input_tokens >= 0)",
        "check(output_tokens >= 0)",
        "check(estimated_cost_microusd >= 0)",
        "status = 'running' and completed_at is null",
        "status in ('completed', 'failed', 'cancelled', 'skipped') and completed_at is not null",
    )
    if any(fragment not in run_sql for fragment in required_run_checks):
        raise RuntimeError("Incompatible agent_runs schema; required constraints are missing")
    if any(fragment not in step_sql for fragment in required_step_checks):
        raise RuntimeError("Incompatible agent_steps schema; required constraints are missing")

    run_foreign_keys = db.execute("PRAGMA foreign_key_list(agent_runs)").fetchall()
    expected_run_foreign_keys = {
        ("chat_sessions", "session_id", "id", "SET NULL"),
        ("chat_messages", "user_message_id", "id", "SET NULL"),
    }
    actual_run_foreign_keys = {
        (row["table"], row["from"], row["to"], row["on_delete"].upper())
        for row in run_foreign_keys
    }
    if actual_run_foreign_keys != expected_run_foreign_keys:
        raise RuntimeError("Incompatible agent_runs schema; foreign keys are incorrect")

    step_foreign_keys = db.execute("PRAGMA foreign_key_list(agent_steps)").fetchall()
    actual_step_foreign_keys = {
        (row["table"], row["from"], row["to"], row["on_delete"].upper())
        for row in step_foreign_keys
    }
    if actual_step_foreign_keys != {
        ("agent_runs", "run_id", "id", "CASCADE")
    }:
        raise RuntimeError("Incompatible agent_steps schema; run cascade is missing")

    for table_name in ("agent_runs", "agent_steps"):
        if db.execute(f"PRAGMA foreign_key_check({table_name})").fetchall():
            raise RuntimeError(
                f"Incompatible {table_name} data; orphaned references exist"
            )


def create_unique_indexes(db: sqlite3.Connection) -> None:
    # Agent request/step keys make retries idempotent. Step numbers provide an
    # immutable order within each run.
    try:
        db.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_request_key
            ON agent_runs(session_id, request_key)
            WHERE request_key IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_steps_run_number
            ON agent_steps(run_id, step_number);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_steps_step_key
            ON agent_steps(run_id, step_key)
            WHERE step_key IS NOT NULL;
            """
        )
    except sqlite3.IntegrityError as exc:
        raise RuntimeError(
            "Cannot enable agent audit idempotency because duplicate run or step "
            "keys/numbers already exist"
        ) from exc


def validate_indexes(db: sqlite3.Connection) -> None:
    expected = {
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
    partial_index_names = {
        "idx_agent_runs_request_key",
        "idx_agent_steps_step_key",
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
            or bool(index["partial"]) is not (index_name in partial_index_names)
            or columns != expected_columns
        ):
            raise RuntimeError(f"Incompatible agent audit index: {index_name}")

    expected_predicates = {
        "idx_agent_runs_request_key": "request_key is not null",
        "idx_agent_steps_step_key": "step_key is not null",
    }
    for index_name, expected_predicate in expected_predicates.items():
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        ).fetchone()
        normalized_sql = " ".join(row["sql"].lower().split()).rstrip(";")
        _, separator, predicate = normalized_sql.partition(" where ")
        if not separator or predicate.strip() != expected_predicate:
            raise RuntimeError(
                f"Incompatible agent audit index: {index_name} has the wrong predicate"
            )
