from __future__ import annotations

import sqlite3

from app.db.schema import table_exists


ACTIVITY_TYPES = (
    "research_started",
    "research_completed",
    "submitted_for_review",
    "changes_requested",
    "approved_for_outreach",
    "linkedin_message_sent",
    "email_sent",
    "follow_up_sent",
    "reply_received",
    "call_scheduled",
    "meeting_completed",
    "proposal_sent",
    "client_decision",
)

CHANNELS = (
    "internal",
    "linkedin",
    "email",
    "phone",
    "video_call",
    "in_person",
    "other",
)

RESPONSE_STATUSES = (
    "not_applicable",
    "awaiting_reply",
    "replied",
    "interested",
    "not_interested",
    "meeting_scheduled",
    "proposal_pending",
    "won",
    "lost",
)

# Shared by the pipeline-transition (Contacted) and lead-activity services.
# Defined here, at the lowest shared level, so neither service module has to
# import the other and duplicate these tuples.
CONTACT_ACTIVITY_TYPES = (
    "linkedin_message_sent",
    "email_sent",
    "follow_up_sent",
    "call_scheduled",
    "meeting_completed",
)
CONTACT_CHANNELS = tuple(
    channel for channel in CHANNELS if channel != "internal"
)
CONTACT_RESPONSE_STATUSES = tuple(
    status for status in RESPONSE_STATUSES if status != "not_applicable"
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS lead_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    activity_type TEXT NOT NULL
        CHECK(activity_type IN ({_sql_values(ACTIVITY_TYPES)})),
    activity_at TEXT NOT NULL
        CHECK(length(trim(activity_at)) > 0),
    channel TEXT NOT NULL DEFAULT 'internal'
        CHECK(channel IN ({_sql_values(CHANNELS)})),
    message_summary TEXT NOT NULL
        CHECK(length(trim(message_summary)) > 0),
    notes TEXT NOT NULL DEFAULT '',
    created_by_user_id INTEGER NOT NULL,
    performed_by_user_id INTEGER NOT NULL,
    responsible_user_id INTEGER,
    response_status TEXT NOT NULL DEFAULT 'not_applicable'
        CHECK(response_status IN ({_sql_values(RESPONSE_STATUSES)})),
    next_follow_up_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    corrected_by_user_id INTEGER,
    correction_reason TEXT NOT NULL DEFAULT '',
    CHECK(
        (corrected_by_user_id IS NULL
         AND length(trim(correction_reason)) = 0)
        OR
        (corrected_by_user_id IS NOT NULL
         AND length(trim(correction_reason)) > 0)
    ),
    CHECK(
        deleted_at IS NULL
        OR
        (corrected_by_user_id IS NOT NULL
         AND length(trim(correction_reason)) > 0)
    ),
    FOREIGN KEY (lead_id)
        REFERENCES leads(id)
        ON DELETE RESTRICT,
    FOREIGN KEY (created_by_user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT,
    FOREIGN KEY (performed_by_user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT,
    FOREIGN KEY (responsible_user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT,
    FOREIGN KEY (corrected_by_user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_lead_activities_lead_timeline
ON lead_activities(
    lead_id,
    deleted_at,
    activity_at DESC,
    id DESC
);

CREATE INDEX IF NOT EXISTS idx_lead_activities_follow_up
ON lead_activities(
    deleted_at,
    next_follow_up_date,
    response_status,
    id
);

CREATE INDEX IF NOT EXISTS idx_lead_activities_responsible_follow_up
ON lead_activities(
    responsible_user_id,
    deleted_at,
    next_follow_up_date,
    id
);

CREATE INDEX IF NOT EXISTS idx_lead_activities_response_activity
ON lead_activities(
    response_status,
    deleted_at,
    activity_at DESC,
    id DESC
);
"""


def _normalized_sql(sql: str) -> str:
    normalized = " ".join(sql.lower().split())
    return normalized.replace("( ", "(").replace(" )", ")")


def validate_schema(db: sqlite3.Connection) -> None:
    """Reject partial or weakened activity schemas without rewriting data."""
    if not table_exists(db, "lead_activities"):
        raise RuntimeError(
            "Incompatible lead activity schema; lead_activities is missing"
        )

    table_info = db.execute(
        "PRAGMA table_info(lead_activities)"
    ).fetchall()
    columns = {row["name"]: row for row in table_info}

    required_columns = {
        "id",
        "lead_id",
        "activity_type",
        "activity_at",
        "channel",
        "message_summary",
        "notes",
        "created_by_user_id",
        "performed_by_user_id",
        "responsible_user_id",
        "response_status",
        "next_follow_up_date",
        "created_at",
        "updated_at",
        "deleted_at",
        "corrected_by_user_id",
        "correction_reason",
    }
    missing = required_columns - set(columns)
    if missing:
        raise RuntimeError(
            "Incompatible lead activity schema; missing columns: "
            + ", ".join(sorted(missing))
        )

    required_not_null = {
        "lead_id",
        "activity_type",
        "activity_at",
        "channel",
        "message_summary",
        "notes",
        "created_by_user_id",
        "performed_by_user_id",
        "response_status",
        "created_at",
        "updated_at",
        "correction_reason",
    }
    nullable = {
        name for name in required_not_null if not columns[name]["notnull"]
    }
    if nullable:
        raise RuntimeError(
            "Incompatible lead activity schema; required columns are nullable: "
            + ", ".join(sorted(nullable))
        )

    must_remain_nullable = {
        "responsible_user_id",
        "next_follow_up_date",
        "deleted_at",
        "corrected_by_user_id",
    }
    incorrectly_required = {
        name for name in must_remain_nullable if columns[name]["notnull"]
    }
    if incorrectly_required:
        raise RuntimeError(
            "Incompatible lead activity schema; columns must be nullable: "
            + ", ".join(sorted(incorrectly_required))
        )

    required_defaults = {
        "channel": "'internal'",
        "notes": "''",
        "response_status": "'not_applicable'",
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "CURRENT_TIMESTAMP",
        "correction_reason": "''",
    }
    wrong_defaults = {
        name
        for name, expected in required_defaults.items()
        if columns[name]["dflt_value"] != expected
    }
    if wrong_defaults:
        raise RuntimeError(
            "Incompatible lead activity schema; columns have incorrect defaults: "
            + ", ".join(sorted(wrong_defaults))
        )

    integer_columns = {
        "id",
        "lead_id",
        "created_by_user_id",
        "performed_by_user_id",
        "responsible_user_id",
        "corrected_by_user_id",
    }
    wrong_integer_types = {
        name
        for name in integer_columns
        if columns[name]["type"].upper() != "INTEGER"
    }
    text_columns = required_columns - integer_columns
    wrong_text_types = {
        name
        for name in text_columns
        if columns[name]["type"].upper() != "TEXT"
    }
    if wrong_integer_types or wrong_text_types:
        wrong = sorted(wrong_integer_types | wrong_text_types)
        raise RuntimeError(
            "Incompatible lead activity schema; wrong column types: "
            + ", ".join(wrong)
        )

    if columns["id"]["pk"] != 1:
        raise RuntimeError(
            "Incompatible lead activity schema; id must be INTEGER PRIMARY KEY"
        )

    table_row = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'lead_activities'
        """
    ).fetchone()
    if table_row is None or table_row["sql"] is None:
        raise RuntimeError(
            "Incompatible lead activity schema; table definition is missing"
        )

    normalized = _normalized_sql(str(table_row["sql"]))
    required_checks = (
        "check(activity_type in (" + _sql_values(ACTIVITY_TYPES) + "))",
        "check(length(trim(activity_at)) > 0)",
        "check(channel in (" + _sql_values(CHANNELS) + "))",
        "check(length(trim(message_summary)) > 0)",
        "check(response_status in (" + _sql_values(RESPONSE_STATUSES) + "))",
        "(corrected_by_user_id is null and length(trim(correction_reason)) = 0) or "
        "(corrected_by_user_id is not null and length(trim(correction_reason)) > 0)",
        "deleted_at is null or (corrected_by_user_id is not null and "
        "length(trim(correction_reason)) > 0)",
    )
    if any(fragment not in normalized for fragment in required_checks):
        raise RuntimeError(
            "Incompatible lead activity schema; required constraints are missing"
        )

    expected_foreign_keys = {
        ("leads", "lead_id", "id", "RESTRICT"),
        ("users", "created_by_user_id", "id", "RESTRICT"),
        ("users", "performed_by_user_id", "id", "RESTRICT"),
        ("users", "responsible_user_id", "id", "RESTRICT"),
        ("users", "corrected_by_user_id", "id", "RESTRICT"),
    }
    actual_foreign_keys = {
        (row["table"], row["from"], row["to"], row["on_delete"].upper())
        for row in db.execute(
            "PRAGMA foreign_key_list(lead_activities)"
        ).fetchall()
    }
    if actual_foreign_keys != expected_foreign_keys:
        raise RuntimeError(
            "Incompatible lead activity schema; audit foreign keys are missing"
        )

    if db.execute("PRAGMA foreign_key_check(lead_activities)").fetchall():
        raise RuntimeError(
            "Incompatible lead activity data; orphaned references exist"
        )


def validate_indexes(db: sqlite3.Connection) -> None:
    expected = {
        "idx_lead_activities_lead_timeline": [
            "lead_id",
            "deleted_at",
            "activity_at",
            "id",
        ],
        "idx_lead_activities_follow_up": [
            "deleted_at",
            "next_follow_up_date",
            "response_status",
            "id",
        ],
        "idx_lead_activities_responsible_follow_up": [
            "responsible_user_id",
            "deleted_at",
            "next_follow_up_date",
            "id",
        ],
        "idx_lead_activities_response_activity": [
            "response_status",
            "deleted_at",
            "activity_at",
            "id",
        ],
    }
    index_rows = {
        row["name"]: row
        for row in db.execute(
            "PRAGMA index_list(lead_activities)"
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
                f"Incompatible lead activity index: {index_name}"
            )
