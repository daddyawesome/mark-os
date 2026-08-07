from __future__ import annotations

import sqlite3

from app.db.schema import column_names, ensure_column, table_exists
from app.services.lead_identity import (
    CREATION_FINGERPRINT_FIELDS,
    lead_creation_fingerprint,
)


CRM_FINGERPRINT_BACKFILL_SENTINEL = "migration-backfill-required"
ORGANIZATION_MIGRATION_KEY = "phase_6_6b_2_lead_organization"

ORGANIZATION_LEAD_COLUMNS = (
    "id",
    "organization_id",
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
    "researched_by_user_id",
    "research_status",
    "submitted_for_review_at",
    "reviewed_by_user_id",
    "reviewed_at",
    "review_notes",
    "outreach_approved_by_user_id",
    "outreach_approved_at",
    "business_development_owner_user_id",
)

_ORGANIZATION_LEADS_TABLE_SQL = """
CREATE TABLE {table_name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    quest_id INTEGER NOT NULL,
    created_by_user_id INTEGER,
    assigned_to_user_id INTEGER,
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
    researched_by_user_id INTEGER,
    research_status TEXT NOT NULL DEFAULT 'draft'
        CHECK(research_status IN (
            'draft', 'researching', 'ready_for_review',
            'changes_requested', 'approved', 'rejected'
        )),
    submitted_for_review_at TEXT,
    reviewed_by_user_id INTEGER,
    reviewed_at TEXT,
    review_notes TEXT NOT NULL DEFAULT '',
    outreach_approved_by_user_id INTEGER,
    outreach_approved_at TEXT,
    business_development_owner_user_id INTEGER,
    FOREIGN KEY (quest_id) REFERENCES tasks(id) ON DELETE RESTRICT,
    FOREIGN KEY (organization_id)
        REFERENCES organizations(id)
        ON DELETE RESTRICT
)
"""

_LEAD_INDEX_DEFINITIONS = (
    """CREATE INDEX idx_leads_pipeline_priority_activity
       ON leads(deleted_at, pipeline_status, priority, updated_at DESC, id DESC)""",
    """CREATE INDEX idx_leads_due_action
       ON leads(deleted_at, next_action_due_date, id)""",
    """CREATE INDEX idx_leads_creator_activity
       ON leads(created_by_user_id, deleted_at, updated_at DESC, id DESC)""",
    """CREATE INDEX idx_leads_assignee_pipeline
       ON leads(assigned_to_user_id, deleted_at, pipeline_status, id DESC)""",
    """CREATE UNIQUE INDEX idx_leads_quest_id ON leads(quest_id)""",
    """CREATE UNIQUE INDEX idx_leads_active_dedupe_key
       ON leads(organization_id, dedupe_key)
       WHERE deleted_at IS NULL""",
    """CREATE UNIQUE INDEX idx_leads_request_key
       ON leads(request_key) WHERE request_key IS NOT NULL""",
    """CREATE INDEX idx_leads_research_queue
       ON leads(deleted_at, research_status, assigned_to_user_id,
                submitted_for_review_at, id DESC)""",
    """CREATE INDEX idx_leads_researcher_activity
       ON leads(researched_by_user_id, deleted_at, updated_at DESC, id DESC)""",
    """CREATE INDEX idx_leads_business_development_owner
       ON leads(business_development_owner_user_id, deleted_at,
                next_action_due_date, id DESC)""",
    """CREATE INDEX idx_leads_organization_id ON leads(organization_id)""",
)

_ACTIVITY_INDEX_DEFINITIONS = (
    """CREATE INDEX idx_lead_activities_lead_timeline
       ON lead_activities(lead_id, deleted_at, activity_at DESC, id DESC)""",
    """CREATE INDEX idx_lead_activities_follow_up
       ON lead_activities(deleted_at, next_follow_up_date, response_status, id)""",
    """CREATE INDEX idx_lead_activities_responsible_follow_up
       ON lead_activities(responsible_user_id, deleted_at,
                          next_follow_up_date, id)""",
    """CREATE INDEX idx_lead_activities_response_activity
       ON lead_activities(response_status, deleted_at, activity_at DESC, id DESC)""",
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_id INTEGER NOT NULL,
    created_by_user_id INTEGER,
    assigned_to_user_id INTEGER,
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

CREATE INDEX IF NOT EXISTS idx_leads_creator_activity
ON leads(created_by_user_id, deleted_at, updated_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_leads_assignee_pipeline
ON leads(assigned_to_user_id, deleted_at, pipeline_status, id DESC);
"""


def validate_schema(
    db: sqlite3.Connection,
    *,
    require_request_fingerprint: bool = True,
    allow_pending_request_fingerprint: bool = False,
    require_ownership: bool = True,
    require_organization: bool = False,
) -> None:
    """Reject partial or weakened lead schemas without rewriting lead data."""
    required_columns = {
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
    if require_organization:
        required_columns.add("organization_id")
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
    if require_organization:
        required_not_null.add("organization_id")
    must_remain_nullable = {
        "request_key",
        "created_by_user_id",
        "assigned_to_user_id",
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

    if not require_ownership:
        required_columns.remove("created_by_user_id")
        required_columns.remove("assigned_to_user_id")
        must_remain_nullable.remove("created_by_user_id")
        must_remain_nullable.remove("assigned_to_user_id")

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

    integer_columns = {"id", "quest_id"}
    if require_organization:
        integer_columns.add("organization_id")
    if require_ownership:
        integer_columns.update(
            {"created_by_user_id", "assigned_to_user_id"}
        )

    wrong_integer_types = {
        name
        for name in integer_columns
        if columns[name]["type"].upper() != "INTEGER"
    }
    if wrong_integer_types:
        type_names = ", ".join(sorted(wrong_integer_types))
        raise RuntimeError(
            f"Incompatible leads schema; columns must be INTEGER: {type_names}"
        )

    text_columns = required_columns - {
        "id",
        "quest_id",
        "organization_id",
        "created_by_user_id",
        "assigned_to_user_id",
    }
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
    expected_foreign_keys = {("tasks", "quest_id", "id", "RESTRICT")}
    if require_organization:
        expected_foreign_keys.add(
            ("organizations", "organization_id", "id", "RESTRICT")
        )
    elif "organization_id" in columns:
        expected_foreign_keys.add(
            ("organizations", "organization_id", "id", "RESTRICT")
        )
    if actual_foreign_keys != expected_foreign_keys:
        raise RuntimeError(
            "Incompatible leads schema; required foreign keys are missing"
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
            require_ownership=False,
            require_organization=False,
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
        validate_schema(
        db,
        require_request_fingerprint=False,
        require_ownership=False,
        require_organization=False,
    )

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



def migrate_ownership(db: sqlite3.Connection) -> None:
    """Add lead ownership only to a complete supported CRM schema.

    Partial or experimental tables must fail closed without being altered.
    This preserves the existing CRM migration guarantee that incompatible
    schemas are rejected without changing their rows or column layout.
    """
    if not table_exists(db, "leads"):
        return

    existing_columns = set(column_names(db, "leads"))

    pre_m4_required_columns = {
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

    if not pre_m4_required_columns.issubset(existing_columns):
        return

    ensure_column(db, "leads", "created_by_user_id", "INTEGER")
    ensure_column(db, "leads", "assigned_to_user_id", "INTEGER")

    if not table_exists(db, "users"):
        return

    owner = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner'
        ORDER BY active DESC, id
        LIMIT 1
        """
    ).fetchone()
    if owner is None:
        return

    owner_id = int(owner["id"])
    db.execute(
        """
        UPDATE leads
        SET
            created_by_user_id = COALESCE(created_by_user_id, ?),
            assigned_to_user_id = COALESCE(assigned_to_user_id, ?)
        WHERE created_by_user_id IS NULL
           OR assigned_to_user_id IS NULL
        """,
        (owner_id, owner_id),
    )


def migrate_organization(db: sqlite3.Connection) -> None:
    """Rebuild leads and its child table with a required organization link."""
    from app.db import lead_activities

    if not table_exists(db, "leads"):
        return

    temporary_tables = {
        "leads__phase_6_6b_2",
        "lead_activities__phase_6_6b_2",
        "leads__phase_6_6b_2_old",
        "lead_activities__phase_6_6b_2_old",
    }
    if any(table_exists(db, table_name) for table_name in temporary_tables):
        raise RuntimeError(
            "Incompatible lead organization migration; temporary tables exist"
        )

    existing_columns = set(column_names(db, "leads"))
    if "organization_id" in existing_columns:
        validate_schema(db, require_organization=True)
        return

    validate_schema(db, require_organization=False)
    lead_activities.validate_schema(db)

    organization_rows = db.execute(
        "SELECT id FROM organizations WHERE slug = ?",
        ("mark-agency",),
    ).fetchall()
    if len(organization_rows) != 1:
        raise RuntimeError(
            "Cannot migrate leads; exactly one mark-agency organization is required"
        )
    organization_id = organization_rows[0]["id"]

    legacy_lead_columns = tuple(
        column for column in ORGANIZATION_LEAD_COLUMNS if column != "organization_id"
    )
    activity_columns = (
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
    )
    old_lead_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    old_activity_count = db.execute(
        "SELECT COUNT(*) FROM lead_activities"
    ).fetchone()[0]
    old_lead_ids = [
        row[0] for row in db.execute("SELECT id FROM leads ORDER BY id")
    ]
    old_activity_ids = [
        row[0]
        for row in db.execute(
            "SELECT id FROM lead_activities ORDER BY id"
        )
    ]
    old_activity_lead_ids = [
        row[0]
        for row in db.execute(
            "SELECT lead_id FROM lead_activities ORDER BY id"
        )
    ]

    db.commit()
    foreign_keys_enabled = bool(
        db.execute("PRAGMA foreign_keys").fetchone()[0]
    )
    legacy_alter_enabled = bool(
        db.execute("PRAGMA legacy_alter_table").fetchone()[0]
    )
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("PRAGMA legacy_alter_table = ON")
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("SAVEPOINT phase_6_6b_2_organization")
        db.execute(
            _ORGANIZATION_LEADS_TABLE_SQL.format(
                table_name="leads__phase_6_6b_2"
            )
        )
        activity_sql = lead_activities.SCHEMA_SQL.replace(
            "CREATE TABLE IF NOT EXISTS lead_activities",
            "CREATE TABLE lead_activities__phase_6_6b_2",
        )
        db.execute(activity_sql)

        lead_column_sql = ", ".join(legacy_lead_columns)
        db.execute(
            f"""
            INSERT INTO leads__phase_6_6b_2
                (organization_id, {lead_column_sql})
            SELECT ?, {lead_column_sql}
            FROM leads
            ORDER BY id
            """,
            (organization_id,),
        )
        activity_column_sql = ", ".join(activity_columns)
        db.execute(
            f"""
            INSERT INTO lead_activities__phase_6_6b_2 ({activity_column_sql})
            SELECT {activity_column_sql}
            FROM lead_activities
            ORDER BY id
            """
        )

        if db.execute(
            "SELECT COUNT(*) FROM leads__phase_6_6b_2"
        ).fetchone()[0] != old_lead_count:
            raise RuntimeError("Lead organization migration changed lead row count")
        if db.execute(
            "SELECT COUNT(*) FROM lead_activities__phase_6_6b_2"
        ).fetchone()[0] != old_activity_count:
            raise RuntimeError(
                "Lead organization migration changed activity row count"
            )
        if [
            row[0]
            for row in db.execute(
                "SELECT id FROM leads__phase_6_6b_2 ORDER BY id"
            )
        ] != old_lead_ids:
            raise RuntimeError("Lead organization migration changed lead IDs")
        if [
            row[0]
            for row in db.execute(
                "SELECT id FROM lead_activities__phase_6_6b_2 ORDER BY id"
            )
        ] != old_activity_ids:
            raise RuntimeError(
                "Lead organization migration changed lead activity IDs"
            )
        if [
            row[0]
            for row in db.execute(
                "SELECT lead_id FROM lead_activities__phase_6_6b_2 ORDER BY id"
            )
        ] != old_activity_lead_ids:
            raise RuntimeError(
                "Lead organization migration changed activity lead links"
            )

        db.execute("DROP TABLE lead_activities")
        db.execute("DROP TABLE leads")
        db.execute(
            "ALTER TABLE leads__phase_6_6b_2 RENAME TO leads"
        )
        db.execute(
            "ALTER TABLE lead_activities__phase_6_6b_2 "
            "RENAME TO lead_activities"
        )
        for index_sql in _LEAD_INDEX_DEFINITIONS + _ACTIVITY_INDEX_DEFINITIONS:
            db.execute(index_sql)

        validate_schema(db, require_organization=True)
        lead_activities.validate_schema(db)
        validate_indexes(db)
        lead_activities.validate_indexes(db)
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError(
                "Lead organization migration produced foreign-key violations"
            )
        db.execute("RELEASE SAVEPOINT phase_6_6b_2_organization")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.execute(
            "PRAGMA legacy_alter_table = "
            + ("ON" if legacy_alter_enabled else "OFF")
        )
        db.execute(
            "PRAGMA foreign_keys = "
            + ("ON" if foreign_keys_enabled else "OFF")
        )

def migrate_workspace_dedupe_index(db: sqlite3.Connection) -> None:
    """Upgrade only the legacy global active-dedupe index to workspace scope."""
    if not table_exists(db, "leads"):
        return
    columns = set(column_names(db, "leads"))
    if "organization_id" not in columns:
        return

    index = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'index'
          AND name = 'idx_leads_active_dedupe_key'
        """
    ).fetchone()
    if index is None:
        return

    index_columns = [
        row["name"]
        for row in db.execute(
            "PRAGMA index_info(idx_leads_active_dedupe_key)"
        ).fetchall()
    ]
    normalized_sql = " ".join(str(index["sql"] or "").lower().split())
    _, separator, predicate = normalized_sql.partition(" where ")

    # Only auto-upgrade the exact pre-workspace index. Any other malformed
    # variant is intentionally left for validate_indexes() to reject.
    if (
        index_columns != ["dedupe_key"]
        or not separator
        or predicate.strip().rstrip(";") != "deleted_at is null"
    ):
        return

    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT crm_workspace_dedupe_index")
    try:
        db.execute("DROP INDEX idx_leads_active_dedupe_key")
        db.execute(
            """
            CREATE UNIQUE INDEX idx_leads_active_dedupe_key
            ON leads(organization_id, dedupe_key)
            WHERE deleted_at IS NULL
            """
        )
    except sqlite3.IntegrityError as exc:
        db.execute("ROLLBACK TO SAVEPOINT crm_workspace_dedupe_index")
        db.execute("RELEASE SAVEPOINT crm_workspace_dedupe_index")
        if owns_transaction:
            db.rollback()
        raise RuntimeError(
            "Cannot enable workspace-scoped CRM duplicate protection because "
            "duplicate active leads already exist inside one organization"
        ) from exc
    except BaseException:
        db.execute("ROLLBACK TO SAVEPOINT crm_workspace_dedupe_index")
        db.execute("RELEASE SAVEPOINT crm_workspace_dedupe_index")
        if owns_transaction:
            db.rollback()
        raise
    else:
        db.execute("RELEASE SAVEPOINT crm_workspace_dedupe_index")


def create_unique_indexes(db: sqlite3.Connection) -> None:
    # Leads keep a single quest link, semantic duplicate key, and network retry
    # key. Soft-deleted leads release only their semantic dedupe key.
    try:
        db.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_quest_id
            ON leads(quest_id);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_active_dedupe_key
            ON leads(organization_id, dedupe_key)
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
        "idx_leads_active_dedupe_key": (
            True,
            ["organization_id", "dedupe_key"],
        ),
        "idx_leads_request_key": (True, ["request_key"]),
        "idx_leads_pipeline_priority_activity": (
            False,
            ["deleted_at", "pipeline_status", "priority", "updated_at", "id"],
        ),
        "idx_leads_due_action": (
            False,
            ["deleted_at", "next_action_due_date", "id"],
        ),
        "idx_leads_creator_activity": (
            False,
            ["created_by_user_id", "deleted_at", "updated_at", "id"],
        ),
        "idx_leads_assignee_pipeline": (
            False,
            ["assigned_to_user_id", "deleted_at", "pipeline_status", "id"],
        ),
        "idx_leads_organization_id": (False, ["organization_id"]),
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
