from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.services.lead_identity import (
    CREATION_FINGERPRINT_FIELDS,
    lead_creation_fingerprint,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("MARK_OS_DB_PATH", str(DATA_DIR / "mark_os.db")))
CRM_FINGERPRINT_BACKFILL_SENTINEL = "migration-backfill-required"


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


# SQLite cannot parameterize identifiers. These private migration helpers are
# safe only because every table/column name comes from hardcoded application
# code. Never pass request data or other user-controlled values to them.
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


def _validate_chat_schema(db: sqlite3.Connection) -> None:
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


def _validate_chat_indexes(db: sqlite3.Connection) -> None:
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


def _validate_agent_audit_schema(db: sqlite3.Connection) -> None:
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


def _validate_agent_audit_indexes(db: sqlite3.Connection) -> None:
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


def _validate_crm_schema(
    db: sqlite3.Connection,
    *,
    require_request_fingerprint: bool = True,
    allow_pending_request_fingerprint: bool = False,
) -> None:
    """Reject partial or weakened lead schemas without rewriting lead data."""
    required_columns = {
        "id",
        "quest_id",
        "request_key",
        "request_fingerprint",
        "dedupe_key",
        "company",
        "contact_person",
        "job_title",
        "source",
        "source_url",
        "problem_opportunity",
        "why_mark_fits",
        "pipeline_status",
        "priority",
        "next_action",
        "next_action_due_date",
        "notes",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    required_not_null = {
        "quest_id",
        "request_fingerprint",
        "dedupe_key",
        "company",
        "contact_person",
        "job_title",
        "source",
        "source_url",
        "problem_opportunity",
        "why_mark_fits",
        "pipeline_status",
        "priority",
        "next_action",
        "notes",
        "created_at",
        "updated_at",
    }
    must_remain_nullable = {
        "request_key",
        "next_action_due_date",
        "deleted_at",
    }
    required_defaults = {
        "job_title": "''",
        "source_url": "''",
        "pipeline_status": "'new'",
        "priority": "'medium'",
        "notes": "''",
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "CURRENT_TIMESTAMP",
    }
    if not require_request_fingerprint:
        required_columns.remove("request_fingerprint")
        required_not_null.remove("request_fingerprint")

    table_info = db.execute("PRAGMA table_info(leads)").fetchall()
    columns = {row["name"]: row for row in table_info}
    missing = required_columns - set(columns)
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise RuntimeError(f"Incompatible leads schema; missing columns: {missing_names}")

    nullable = {
        name for name in required_not_null if not columns[name]["notnull"]
    }
    if nullable:
        nullable_names = ", ".join(sorted(nullable))
        raise RuntimeError(
            "Incompatible leads schema; required columns are nullable: "
            f"{nullable_names}"
        )

    incorrectly_required = {
        name for name in must_remain_nullable if columns[name]["notnull"]
    }
    if incorrectly_required:
        required_names = ", ".join(sorted(incorrectly_required))
        raise RuntimeError(
            f"Incompatible leads schema; columns must be nullable: {required_names}"
        )

    wrong_defaults = {
        name
        for name, expected_default in required_defaults.items()
        if columns[name]["dflt_value"] != expected_default
    }
    if wrong_defaults:
        default_names = ", ".join(sorted(wrong_defaults))
        raise RuntimeError(
            f"Incompatible leads schema; columns have incorrect defaults: {default_names}"
        )

    wrong_integer_types = {
        name
        for name in ("id", "quest_id")
        if columns[name]["type"].upper() != "INTEGER"
    }
    if wrong_integer_types:
        type_names = ", ".join(sorted(wrong_integer_types))
        raise RuntimeError(
            f"Incompatible leads schema; columns must be INTEGER: {type_names}"
        )

    text_columns = required_columns - {"id", "quest_id"}
    wrong_text_types = {
        name
        for name in text_columns
        if columns[name]["type"].upper() != "TEXT"
    }
    if wrong_text_types:
        type_names = ", ".join(sorted(wrong_text_types))
        raise RuntimeError(
            f"Incompatible leads schema; columns must be TEXT: {type_names}"
        )

    if columns["id"]["pk"] != 1:
        raise RuntimeError(
            "Incompatible leads schema; id must be INTEGER PRIMARY KEY"
        )

    table_row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'leads'"
    ).fetchone()
    normalized_sql = " ".join(table_row["sql"].lower().split())
    normalized_sql = normalized_sql.replace("( ", "(").replace(" )", ")")
    required_checks = [
        "check(length(trim(dedupe_key)) > 0)",
        "check(length(trim(company)) > 0)",
        "check(length(trim(contact_person)) > 0)",
        "check(length(trim(source)) > 0)",
        "check(length(trim(problem_opportunity)) > 0)",
        "check(length(trim(why_mark_fits)) > 0)",
        "check(length(trim(next_action)) > 0)",
        "check(pipeline_status in ('new', 'reviewed', 'contacted', 'replied', 'meeting', 'proposal', 'won', 'lost'))",
        "check(priority in ('high', 'medium', 'low'))",
    ]
    if require_request_fingerprint:
        required_checks.append("check(length(trim(request_fingerprint)) > 0)")
    if any(fragment not in normalized_sql for fragment in required_checks):
        raise RuntimeError("Incompatible leads schema; required constraints are missing")

    foreign_keys = db.execute("PRAGMA foreign_key_list(leads)").fetchall()
    actual_foreign_keys = {
        (row["table"], row["from"], row["to"], row["on_delete"].upper())
        for row in foreign_keys
    }
    if actual_foreign_keys != {("tasks", "quest_id", "id", "RESTRICT")}:
        raise RuntimeError(
            "Incompatible leads schema; quest restrict foreign key is missing"
        )

    if db.execute("PRAGMA foreign_key_check(leads)").fetchall():
        raise RuntimeError("Incompatible leads data; orphaned quest references exist")
    if require_request_fingerprint and not allow_pending_request_fingerprint:
        pending = db.execute(
            """
            SELECT id FROM leads
            WHERE request_fingerprint = ?
            LIMIT 1
            """,
            (CRM_FINGERPRINT_BACKFILL_SENTINEL,),
        ).fetchone()
        if pending:
            raise RuntimeError(
                "Incompatible leads data; request fingerprints need migration"
            )


def _migrate_crm_request_fingerprint(db: sqlite3.Connection) -> None:
    """Upgrade the immediately previous CRM schema without rebuilding lead data."""
    if not _table_exists(db, "leads"):
        return
    has_fingerprint = "request_fingerprint" in _column_names(db, "leads")
    if has_fingerprint:
        _validate_crm_schema(
            db,
            allow_pending_request_fingerprint=True,
        )
        pending_count = db.execute(
            "SELECT COUNT(*) FROM leads WHERE request_fingerprint = ?",
            (CRM_FINGERPRINT_BACKFILL_SENTINEL,),
        ).fetchone()[0]
        if not pending_count:
            return
    else:
        # Only upgrade the complete prior schema. Partial/experimental tables
        # must continue to fail closed without being rewritten.
        _validate_crm_schema(db, require_request_fingerprint=False)

    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT crm_fingerprint_migration")
    try:
        if not has_fingerprint:
            db.execute(
                f"""
                ALTER TABLE leads
                ADD COLUMN request_fingerprint TEXT NOT NULL
                    DEFAULT '{CRM_FINGERPRINT_BACKFILL_SENTINEL}'
                    CHECK(length(trim(request_fingerprint)) > 0)
                """
            )

        # These identifiers come only from the hardcoded identity-field tuple;
        # never include request or other user-controlled values in this SQL.
        selected_fields = ", ".join(CREATION_FINGERPRINT_FIELDS)
        rows = db.execute(
            f"""
            SELECT id, {selected_fields}
            FROM leads
            WHERE request_fingerprint = ?
            ORDER BY id
            """,
            (CRM_FINGERPRINT_BACKFILL_SENTINEL,),
        ).fetchall()
        for row in rows:
            values = {field: row[field] for field in CREATION_FINGERPRINT_FIELDS}
            db.execute(
                "UPDATE leads SET request_fingerprint = ? WHERE id = ?",
                (lead_creation_fingerprint(values), row["id"]),
            )

        remaining = db.execute(
            "SELECT COUNT(*) FROM leads WHERE request_fingerprint = ?",
            (CRM_FINGERPRINT_BACKFILL_SENTINEL,),
        ).fetchone()[0]
        if remaining:
            raise RuntimeError("CRM request fingerprint backfill was incomplete")
    except BaseException:
        db.execute("ROLLBACK TO SAVEPOINT crm_fingerprint_migration")
        db.execute("RELEASE SAVEPOINT crm_fingerprint_migration")
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute("RELEASE SAVEPOINT crm_fingerprint_migration")


def _validate_crm_indexes(db: sqlite3.Connection) -> None:
    expected = {
        "idx_leads_quest_id": (True, ["quest_id"]),
        "idx_leads_active_dedupe_key": (True, ["dedupe_key"]),
        "idx_leads_request_key": (True, ["request_key"]),
        "idx_leads_pipeline_priority_activity": (
            False,
            ["deleted_at", "pipeline_status", "priority", "updated_at", "id"],
        ),
        "idx_leads_due_action": (
            False,
            ["deleted_at", "next_action_due_date", "id"],
        ),
    }
    partial_index_names = {
        "idx_leads_active_dedupe_key",
        "idx_leads_request_key",
    }

    index_rows = {
        row["name"]: row
        for row in db.execute("PRAGMA index_list(leads)").fetchall()
    }
    for index_name, (must_be_unique, expected_columns) in expected.items():
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
            raise RuntimeError(f"Incompatible CRM index: {index_name}")

    expected_predicates = {
        "idx_leads_active_dedupe_key": "deleted_at is null",
        "idx_leads_request_key": "request_key is not null",
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
                f"Incompatible CRM index: {index_name} has the wrong predicate"
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

            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quest_id INTEGER NOT NULL,
                request_key TEXT,
                request_fingerprint TEXT NOT NULL
                    CHECK(length(trim(request_fingerprint)) > 0),
                dedupe_key TEXT NOT NULL CHECK(length(trim(dedupe_key)) > 0),
                company TEXT NOT NULL CHECK(length(trim(company)) > 0),
                contact_person TEXT NOT NULL
                    CHECK(length(trim(contact_person)) > 0),
                job_title TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL CHECK(length(trim(source)) > 0),
                source_url TEXT NOT NULL DEFAULT '',
                problem_opportunity TEXT NOT NULL
                    CHECK(length(trim(problem_opportunity)) > 0),
                why_mark_fits TEXT NOT NULL
                    CHECK(length(trim(why_mark_fits)) > 0),
                pipeline_status TEXT NOT NULL DEFAULT 'new'
                    CHECK(pipeline_status IN (
                        'new', 'reviewed', 'contacted', 'replied',
                        'meeting', 'proposal', 'won', 'lost'
                    )),
                priority TEXT NOT NULL DEFAULT 'medium'
                    CHECK(priority IN ('high', 'medium', 'low')),
                next_action TEXT NOT NULL CHECK(length(trim(next_action)) > 0),
                next_action_due_date TEXT,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                deleted_at TEXT,
                FOREIGN KEY (quest_id) REFERENCES tasks(id) ON DELETE RESTRICT
            );

            """
        )

        _validate_chat_schema(db)
        _validate_agent_audit_schema(db)
        _migrate_crm_request_fingerprint(db)
        _validate_crm_schema(db)

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

        _ensure_column(db, "checkins", "cash_in", "REAL")
        _ensure_column(db, "checkins", "updated_at", "TEXT")
        
        db.execute(
            """
            UPDATE checkins
            SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
            WHERE updated_at IS NULL OR updated_at = ''
            """
        )

        # Create ordinary indexes only after all legacy-schema migrations.
        db.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_checkins_date
            ON checkins(checkin_date);

            CREATE INDEX IF NOT EXISTS idx_timeline_events_date
            ON timeline_events(event_date);

            CREATE INDEX IF NOT EXISTS idx_timeline_events_type
            ON timeline_events(event_type);

            CREATE INDEX IF NOT EXISTS idx_memories_type
            ON memories(memory_type);

            CREATE INDEX IF NOT EXISTS idx_tasks_status
            ON tasks(status);

            CREATE INDEX IF NOT EXISTS idx_tasks_project
            ON tasks(project_id);

            CREATE INDEX IF NOT EXISTS idx_tasks_goal
            ON tasks(goal_id);

            CREATE INDEX IF NOT EXISTS idx_quest_updates_task
            ON quest_updates(task_id);

            CREATE INDEX IF NOT EXISTS idx_chat_sessions_status_activity
            ON chat_sessions(status, last_message_at DESC, updated_at DESC, id DESC);

            CREATE INDEX IF NOT EXISTS idx_chat_messages_recent
            ON chat_messages(session_id, deleted_at, created_at DESC, id DESC);

            CREATE INDEX IF NOT EXISTS idx_agent_runs_session_created
            ON agent_runs(session_id, created_at DESC, id DESC);

            CREATE INDEX IF NOT EXISTS idx_agent_runs_user_message_created
            ON agent_runs(user_message_id, created_at DESC, id DESC);

            CREATE INDEX IF NOT EXISTS idx_agent_runs_status_updated
            ON agent_runs(status, updated_at DESC, id DESC);

            CREATE INDEX IF NOT EXISTS idx_leads_pipeline_priority_activity
            ON leads(
                deleted_at,
                pipeline_status,
                priority,
                updated_at DESC,
                id DESC
            );

            CREATE INDEX IF NOT EXISTS idx_leads_due_action
            ON leads(deleted_at, next_action_due_date, id);
            """
        )

        # Create this index only after event_key is guaranteed to exist.
        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_xp_ledger_event_key
            ON xp_ledger(event_key)
            WHERE event_key IS NOT NULL
            """
        )

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

        # Agent request/step keys make retries idempotent. Step numbers provide
        # an immutable order within each run.
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

        # Leads keep a single quest link, semantic duplicate key, and network
        # retry key. Soft-deleted leads release only their semantic dedupe key.
        try:
            db.executescript(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_quest_id
                ON leads(quest_id);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_active_dedupe_key
                ON leads(dedupe_key)
                WHERE deleted_at IS NULL;

                CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_request_key
                ON leads(request_key)
                WHERE request_key IS NOT NULL;
                """
            )
        except sqlite3.IntegrityError as exc:
            raise RuntimeError(
                "Cannot enable CRM link or duplicate protection because duplicate "
                "quest, dedupe, or request keys already exist"
            ) from exc

        _validate_chat_indexes(db)
        _validate_agent_audit_indexes(db)
        _validate_crm_indexes(db)

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
