from __future__ import annotations

import sqlite3

from app.db.schema import column_names, ensure_column, table_exists


RESEARCH_STATUSES = (
    "draft",
    "researching",
    "ready_for_review",
    "changes_requested",
    "approved",
    "rejected",
)

RESEARCH_WORKFLOW_COLUMNS = (
    "researched_by_user_id",
    "research_status",
    "submitted_for_review_at",
    "reviewed_by_user_id",
    "reviewed_at",
    "review_notes",
    "outreach_approved_by_user_id",
    "outreach_approved_at",
)

MIGRATION_KEY = "phase_6_1a_research_workflow"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS crm_schema_migrations (
    migration_key TEXT PRIMARY KEY
        CHECK(length(trim(migration_key)) > 0),
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_leads_research_queue
ON leads(
    deleted_at,
    research_status,
    assigned_to_user_id,
    submitted_for_review_at,
    id DESC
);

CREATE INDEX IF NOT EXISTS idx_leads_researcher_activity
ON leads(
    researched_by_user_id,
    deleted_at,
    updated_at DESC,
    id DESC
);
"""


def _migration_applied(
    db: sqlite3.Connection,
) -> bool:
    row = db.execute(
        """
        SELECT 1
        FROM crm_schema_migrations
        WHERE migration_key = ?
        """,
        (MIGRATION_KEY,),
    ).fetchone()
    return row is not None


def _mark_migration_applied(
    db: sqlite3.Connection,
) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO crm_schema_migrations (
            migration_key
        )
        VALUES (?)
        """,
        (MIGRATION_KEY,),
    )


def _primary_owner_id(
    db: sqlite3.Connection,
) -> int | None:
    if not table_exists(db, "users"):
        return None

    row = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner'
        ORDER BY active DESC, id
        LIMIT 1
        """
    ).fetchone()
    return None if row is None else int(row["id"])


def _backfill_existing_leads(
    db: sqlite3.Connection,
) -> None:
    owner_id = _primary_owner_id(db)

    db.execute(
        """
        UPDATE leads
        SET
            researched_by_user_id = COALESCE(
                researched_by_user_id,
                created_by_user_id,
                assigned_to_user_id
            ),
            research_status = 'approved',
            reviewed_by_user_id = COALESCE(
                reviewed_by_user_id,
                ?
            ),
            reviewed_at = COALESCE(
                reviewed_at,
                updated_at,
                created_at,
                CURRENT_TIMESTAMP
            ),
            review_notes = CASE
                WHEN length(trim(review_notes)) = 0
                THEN 'Approved during Phase 6.1 migration.'
                ELSE review_notes
            END,
            outreach_approved_by_user_id = COALESCE(
                outreach_approved_by_user_id,
                ?
            ),
            outreach_approved_at = COALESCE(
                outreach_approved_at,
                updated_at,
                created_at,
                CURRENT_TIMESTAMP
            )
        """,
        (owner_id, owner_id),
    )


def migrate(
    db: sqlite3.Connection,
) -> None:
    """Add Phase 6.1 research fields without replacing lead data."""
    if not table_exists(db, "leads"):
        return

    existing = set(column_names(db, "leads"))
    required = set(RESEARCH_WORKFLOW_COLUMNS)
    present = existing & required

    if present and present != required:
        missing = ", ".join(sorted(required - present))
        raise RuntimeError(
            "Incompatible partial CRM research schema; "
            f"missing columns: {missing}"
        )

    supported_base_columns = {
        "id",
        "quest_id",
        "created_by_user_id",
        "assigned_to_user_id",
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
    if not supported_base_columns.issubset(existing):
        # The existing leads validator owns rejection of unsupported
        # partial/experimental schemas.
        return

    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")

    db.execute("SAVEPOINT phase_6_1a_research")

    try:
        if not present:
            ensure_column(
                db,
                "leads",
                "researched_by_user_id",
                "INTEGER",
            )
            ensure_column(
                db,
                "leads",
                "research_status",
                (
                    "TEXT NOT NULL DEFAULT 'draft' "
                    "CHECK(research_status IN ("
                    "'draft', 'researching', "
                    "'ready_for_review', "
                    "'changes_requested', "
                    "'approved', 'rejected'))"
                ),
            )
            ensure_column(
                db,
                "leads",
                "submitted_for_review_at",
                "TEXT",
            )
            ensure_column(
                db,
                "leads",
                "reviewed_by_user_id",
                "INTEGER",
            )
            ensure_column(
                db,
                "leads",
                "reviewed_at",
                "TEXT",
            )
            ensure_column(
                db,
                "leads",
                "review_notes",
                "TEXT NOT NULL DEFAULT ''",
            )
            ensure_column(
                db,
                "leads",
                "outreach_approved_by_user_id",
                "INTEGER",
            )
            ensure_column(
                db,
                "leads",
                "outreach_approved_at",
                "TEXT",
            )

        if not _migration_applied(db):
            _backfill_existing_leads(db)
            _mark_migration_applied(db)

    except BaseException:
        db.execute(
            "ROLLBACK TO SAVEPOINT phase_6_1a_research"
        )
        db.execute(
            "RELEASE SAVEPOINT phase_6_1a_research"
        )
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute(
            "RELEASE SAVEPOINT phase_6_1a_research"
        )


def validate_schema(
    db: sqlite3.Connection,
) -> None:
    if not table_exists(db, "crm_schema_migrations"):
        raise RuntimeError(
            "Incompatible CRM research schema; "
            "migration table is missing"
        )

    table_info = db.execute(
        "PRAGMA table_info(leads)"
    ).fetchall()
    columns = {
        row["name"]: row
        for row in table_info
    }

    missing = (
        set(RESEARCH_WORKFLOW_COLUMNS)
        - set(columns)
    )
    if missing:
        raise RuntimeError(
            "Incompatible CRM research schema; "
            f"missing columns: {', '.join(sorted(missing))}"
        )

    integer_columns = {
        "researched_by_user_id",
        "reviewed_by_user_id",
        "outreach_approved_by_user_id",
    }
    text_columns = (
        set(RESEARCH_WORKFLOW_COLUMNS)
        - integer_columns
    )

    wrong_integer_types = {
        name
        for name in integer_columns
        if columns[name]["type"].upper() != "INTEGER"
    }
    wrong_text_types = {
        name
        for name in text_columns
        if columns[name]["type"].upper() != "TEXT"
    }
    if wrong_integer_types or wrong_text_types:
        wrong = sorted(
            wrong_integer_types | wrong_text_types
        )
        raise RuntimeError(
            "Incompatible CRM research schema; "
            f"wrong column types: {', '.join(wrong)}"
        )

    if columns["research_status"]["notnull"] != 1:
        raise RuntimeError(
            "Incompatible CRM research schema; "
            "research_status must be required"
        )
    if columns["review_notes"]["notnull"] != 1:
        raise RuntimeError(
            "Incompatible CRM research schema; "
            "review_notes must be required"
        )
    if (
        columns["research_status"]["dflt_value"]
        != "'draft'"
    ):
        raise RuntimeError(
            "Incompatible CRM research schema; "
            "research_status default must be draft"
        )
    if columns["review_notes"]["dflt_value"] != "''":
        raise RuntimeError(
            "Incompatible CRM research schema; "
            "review_notes default must be empty"
        )

    table_row = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'leads'
        """
    ).fetchone()
    normalized = " ".join(
        str(table_row["sql"]).lower().split()
    )
    normalized = normalized.replace(
        "( ",
        "(",
    ).replace(
        " )",
        ")",
    )
    required_check = (
        "check(research_status in "
        "('draft', 'researching', "
        "'ready_for_review', "
        "'changes_requested', "
        "'approved', 'rejected'))"
    )
    if required_check not in normalized:
        raise RuntimeError(
            "Incompatible CRM research schema; "
            "research_status constraint is missing"
        )

    if not _migration_applied(db):
        raise RuntimeError(
            "Incompatible CRM research schema; "
            "backfill marker is missing"
        )


def validate_indexes(
    db: sqlite3.Connection,
) -> None:
    expected = {
        "idx_leads_research_queue": [
            "deleted_at",
            "research_status",
            "assigned_to_user_id",
            "submitted_for_review_at",
            "id",
        ],
        "idx_leads_researcher_activity": [
            "researched_by_user_id",
            "deleted_at",
            "updated_at",
            "id",
        ],
    }

    index_rows = {
        row["name"]: row
        for row in db.execute(
            "PRAGMA index_list(leads)"
        ).fetchall()
    }

    for index_name, expected_columns in expected.items():
        index = index_rows.get(index_name)
        columns = [
            row["name"]
            for row in db.execute(
                f"PRAGMA index_info({index_name})"
            ).fetchall()
        ]
        if (
            index is None
            or bool(index["unique"])
            or bool(index["partial"])
            or columns != expected_columns
        ):
            raise RuntimeError(
                f"Incompatible CRM research index: "
                f"{index_name}"
            )
