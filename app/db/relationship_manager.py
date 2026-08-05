from __future__ import annotations

import sqlite3

from app.db.schema import column_names, ensure_column, table_exists


LEAD_RELATIONSHIP_COLUMN = "business_development_owner_user_id"

SCHEMA_SQL = ""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_leads_business_development_owner
ON leads(
    business_development_owner_user_id,
    deleted_at,
    next_action_due_date,
    id DESC
);
"""


def migrate(db: sqlite3.Connection) -> None:
    """Add Relationship Manager ownership without rewriting lead rows."""
    if not table_exists(db, "leads"):
        return

    ensure_column(
        db,
        "leads",
        LEAD_RELATIONSHIP_COLUMN,
        "INTEGER",
    )


def validate_schema(db: sqlite3.Connection) -> None:
    if not table_exists(db, "leads"):
        raise RuntimeError(
            "Incompatible Relationship Manager schema; leads is missing"
        )

    columns = {
        row["name"]: row
        for row in db.execute("PRAGMA table_info(leads)").fetchall()
    }
    column = columns.get(LEAD_RELATIONSHIP_COLUMN)
    if column is None:
        raise RuntimeError(
            "Incompatible Relationship Manager schema; "
            f"missing column: {LEAD_RELATIONSHIP_COLUMN}"
        )
    if column["type"].upper() != "INTEGER":
        raise RuntimeError(
            "Incompatible Relationship Manager schema; "
            "business development owner must be INTEGER"
        )
    if column["notnull"]:
        raise RuntimeError(
            "Incompatible Relationship Manager schema; "
            "business development owner must remain nullable"
        )
    if column["dflt_value"] is not None:
        raise RuntimeError(
            "Incompatible Relationship Manager schema; "
            "business development owner must not have a default"
        )


def validate_indexes(db: sqlite3.Connection) -> None:
    rows = {
        row["name"]: row
        for row in db.execute("PRAGMA index_list(leads)").fetchall()
    }
    index_name = "idx_leads_business_development_owner"
    index = rows.get(index_name)
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
        or columns
        != [
            "business_development_owner_user_id",
            "deleted_at",
            "next_action_due_date",
            "id",
        ]
    ):
        raise RuntimeError(
            "Incompatible Relationship Manager index: "
            f"{index_name}"
        )
