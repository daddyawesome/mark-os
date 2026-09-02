from __future__ import annotations

import sqlite3

from app.db.schema import column_names, ensure_column, table_exists


QUALIFICATION_STATUSES = (
    "not_started",
    "in_progress",
    "qualified",
    "disqualified",
)

QUALIFICATION_TEXT_COLUMNS = (
    "business_problem",
    "business_impact",
    "current_process",
    "current_tools",
    "estimated_hours_wasted",
    "urgency",
    "budget_range",
    "decision_maker",
    "desired_result",
    "meeting_notes",
    "recommended_service",
)

QUALIFICATION_COLUMNS = QUALIFICATION_TEXT_COLUMNS + (
    "qualification_status",
    "qualification_updated_by_user_id",
    "qualification_updated_at",
    "qualification_decided_by_user_id",
    "qualification_decided_at",
)


def migrate(db: sqlite3.Connection) -> None:
    """Add Phase 6.9 discovery/qualification fields without rebuilding leads."""
    if not table_exists(db, "leads"):
        return

    existing = set(column_names(db, "leads"))
    required = set(QUALIFICATION_COLUMNS)
    present = existing & required
    if present and present != required:
        missing = ", ".join(sorted(required - present))
        raise RuntimeError(
            "Incompatible partial CRM qualification schema; "
            f"missing columns: {missing}"
        )
    if present == required:
        return

    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT phase_6_9_qualification")

    try:
        for column in QUALIFICATION_TEXT_COLUMNS:
            ensure_column(db, "leads", column, "TEXT NOT NULL DEFAULT ''")
        ensure_column(
            db,
            "leads",
            "qualification_status",
            (
                "TEXT NOT NULL DEFAULT 'not_started' "
                "CHECK(qualification_status IN ("
                "'not_started', 'in_progress', "
                "'qualified', 'disqualified'))"
            ),
        )
        ensure_column(
            db, "leads", "qualification_updated_by_user_id", "INTEGER"
        )
        ensure_column(db, "leads", "qualification_updated_at", "TEXT")
        ensure_column(
            db, "leads", "qualification_decided_by_user_id", "INTEGER"
        )
        ensure_column(db, "leads", "qualification_decided_at", "TEXT")
    except BaseException:
        db.execute("ROLLBACK TO SAVEPOINT phase_6_9_qualification")
        db.execute("RELEASE SAVEPOINT phase_6_9_qualification")
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute("RELEASE SAVEPOINT phase_6_9_qualification")


def validate_schema(db: sqlite3.Connection) -> None:
    if not table_exists(db, "leads"):
        raise RuntimeError(
            "Incompatible CRM qualification schema; leads table is missing"
        )
    columns = set(column_names(db, "leads"))
    missing = set(QUALIFICATION_COLUMNS) - columns
    if missing:
        raise RuntimeError(
            "Incompatible CRM qualification schema; missing columns: "
            + ", ".join(sorted(missing))
        )
