from __future__ import annotations

import sqlite3

from app.db.schema import column_names, table_exists
from app.services.lead_identity import (
    CREATION_FINGERPRINT_FIELDS,
    lead_creation_fingerprint,
)


CRM_FINGERPRINT_BACKFILL_SENTINEL = "migration-backfill-required"


SCHEMA_SQL = """
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


INDEX_SQL = """
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


def validate_schema(
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
        "check(pipeline_status in ('new', 'reviewed', 'contacted', 'replied', "
        "'meeting', 'proposal', 'won', 'lost'))",
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


def migrate_request_fingerprint(db: sqlite3.Connection) -> None:
    """Upgrade the immediately previous CRM schema without rebuilding lead data."""
    if not table_exists(db, "leads"):
        return
    has_fingerprint = "request_fingerprint" in column_names(db, "leads")
    if has_fingerprint:
        validate_schema(
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
        validate_schema(db, require_request_fingerprint=False)

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


def create_unique_indexes(db: sqlite3.Connection) -> None:
    # Leads keep a single quest link, semantic duplicate key, and network retry
    # key. Soft-deleted leads release only their semantic dedupe key.
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


def validate_indexes(db: sqlite3.Connection) -> None:
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
