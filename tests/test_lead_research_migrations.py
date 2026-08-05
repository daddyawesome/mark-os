from __future__ import annotations

import sqlite3

import pytest

from app import database
from app.db.lead_research import MIGRATION_KEY


RESEARCH_COLUMNS = (
    "researched_by_user_id",
    "research_status",
    "submitted_for_review_at",
    "reviewed_by_user_id",
    "reviewed_at",
    "review_notes",
    "outreach_approved_by_user_id",
    "outreach_approved_at",
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv(
        "MARK_OS_USERNAME",
        "mark",
    )
    monkeypatch.setenv(
        "MARK_OS_PASSWORD",
        "owner-password-123",
    )
    monkeypatch.setenv(
        "MARK_OS_DISPLAY_NAME",
        "Mark",
    )


def _connect(path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _replace_with_pre_phase_6_1_table(
    db: sqlite3.Connection,
) -> None:
    db.execute("DROP TABLE leads")
    db.executescript(
        """
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quest_id INTEGER NOT NULL,
            created_by_user_id INTEGER,
            assigned_to_user_id INTEGER,
            request_key TEXT,
            request_fingerprint TEXT NOT NULL
                CHECK(length(trim(request_fingerprint)) > 0),
            dedupe_key TEXT NOT NULL
                CHECK(length(trim(dedupe_key)) > 0),
            company TEXT NOT NULL
                CHECK(length(trim(company)) > 0),
            contact_person TEXT NOT NULL
                CHECK(length(trim(contact_person)) > 0),
            job_title TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL
                CHECK(length(trim(source)) > 0),
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
            next_action TEXT NOT NULL
                CHECK(length(trim(next_action)) > 0),
            next_action_due_date TEXT,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleted_at TEXT,
            FOREIGN KEY (quest_id)
                REFERENCES tasks(id)
                ON DELETE RESTRICT
        );
        """
    )
    db.execute(
        """
        DELETE FROM crm_schema_migrations
        WHERE migration_key = ?
        """,
        (MIGRATION_KEY,),
    )


def test_fresh_database_has_research_schema(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "fresh-research.db"
    monkeypatch.setattr(
        database,
        "DB_PATH",
        database_path,
    )
    _configure_owner(monkeypatch)

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    columns = {
        row["name"]: row
        for row in db.execute(
            "PRAGMA table_info(leads)"
        ).fetchall()
    }

    assert set(RESEARCH_COLUMNS).issubset(columns)
    assert columns["research_status"]["notnull"] == 1
    assert (
        columns["research_status"]["dflt_value"]
        == "'draft'"
    )
    assert columns["review_notes"]["notnull"] == 1
    assert (
        columns["review_notes"]["dflt_value"]
        == "''"
    )

    marker = db.execute(
        """
        SELECT migration_key
        FROM crm_schema_migrations
        WHERE migration_key = ?
        """,
        (MIGRATION_KEY,),
    ).fetchone()
    assert marker["migration_key"] == MIGRATION_KEY

    indexes = {
        row["name"]
        for row in db.execute(
            "PRAGMA index_list(leads)"
        ).fetchall()
    }
    assert "idx_leads_research_queue" in indexes
    assert (
        "idx_leads_researcher_activity"
        in indexes
    )

    assert db.execute(
        "PRAGMA quick_check"
    ).fetchone()[0] == "ok"
    assert db.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []
    db.close()


def test_new_lead_defaults_to_draft(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "new-lead-draft.db"
    monkeypatch.setattr(
        database,
        "DB_PATH",
        database_path,
    )
    _configure_owner(monkeypatch)
    database.init_db()

    db = _connect(database_path)
    owner_id = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner'
        """
    ).fetchone()["id"]

    quest_id = db.execute(
        """
        INSERT INTO tasks (
            user_id,
            title,
            description,
            status,
            quest_source,
            why
        )
        VALUES (
            ?,
            'Research new lead',
            'Verify Phase 6.1 defaults.',
            'backlog',
            'client_hunting',
            'New research must start as draft.'
        )
        """,
        (owner_id,),
    ).lastrowid

    lead_id = db.execute(
        """
        INSERT INTO leads (
            quest_id,
            created_by_user_id,
            assigned_to_user_id,
            request_fingerprint,
            dedupe_key,
            company,
            contact_person,
            source,
            problem_opportunity,
            why_mark_fits,
            next_action
        )
        VALUES (
            ?, ?, ?,
            'v1:new-draft-fingerprint',
            'v1:new-draft-lead',
            'Draft Analytics',
            'Dana Buyer',
            'LinkedIn',
            'Reporting is manual.',
            'Mark can automate it.',
            'Complete research.'
        )
        """,
        (quest_id, owner_id, owner_id),
    ).lastrowid
    db.commit()

    lead = db.execute(
        """
        SELECT
            research_status,
            review_notes,
            reviewed_by_user_id,
            outreach_approved_by_user_id
        FROM leads
        WHERE id = ?
        """,
        (lead_id,),
    ).fetchone()

    assert lead["research_status"] == "draft"
    assert lead["review_notes"] == ""
    assert lead["reviewed_by_user_id"] is None
    assert (
        lead["outreach_approved_by_user_id"]
        is None
    )
    db.close()


def test_existing_lead_is_backfilled_as_approved(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "legacy-research.db"
    monkeypatch.setattr(
        database,
        "DB_PATH",
        database_path,
    )
    _configure_owner(monkeypatch)
    database.init_db()

    db = _connect(database_path)
    owner_id = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner'
        """
    ).fetchone()["id"]

    brother_id = db.execute(
        """
        INSERT INTO users (
            username,
            display_name,
            password_hash,
            role,
            active,
            must_change_password
        )
        VALUES (
            'brother',
            'Brother',
            'test-only-hash',
            'lead_sourcer',
            1,
            1
        )
        """
    ).lastrowid

    _replace_with_pre_phase_6_1_table(db)

    quest_id = db.execute(
        """
        INSERT INTO tasks (
            user_id,
            title,
            description,
            status,
            quest_source,
            why
        )
        VALUES (
            ?,
            'Preserve existing lead',
            'Lead existed before Phase 6.1.',
            'backlog',
            'client_hunting',
            'Migration must preserve CRM data.'
        )
        """,
        (owner_id,),
    ).lastrowid

    lead_id = db.execute(
        """
        INSERT INTO leads (
            quest_id,
            created_by_user_id,
            assigned_to_user_id,
            request_key,
            request_fingerprint,
            dedupe_key,
            company,
            contact_person,
            source,
            problem_opportunity,
            why_mark_fits,
            pipeline_status,
            priority,
            next_action,
            notes,
            created_at,
            updated_at
        )
        VALUES (
            ?, ?, ?,
            'legacy-request',
            'v1:legacy-fingerprint',
            'v1:legacy-research',
            'Legacy Analytics',
            'Alex Buyer',
            'LinkedIn',
            'Manual reporting is slow.',
            'Mark can automate it.',
            'contacted',
            'high',
            'Follow up with Alex.',
            'Preserve this note.',
            '2026-08-01 08:00:00',
            '2026-08-02 09:30:00'
        )
        """,
        (quest_id, brother_id, owner_id),
    ).lastrowid
    db.commit()
    db.close()

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    lead = db.execute(
        """
        SELECT *
        FROM leads
        WHERE id = ?
        """,
        (lead_id,),
    ).fetchone()

    assert lead["company"] == "Legacy Analytics"
    assert lead["notes"] == "Preserve this note."
    assert (
        lead["researched_by_user_id"]
        == brother_id
    )
    assert lead["research_status"] == "approved"
    assert (
        lead["reviewed_by_user_id"]
        == owner_id
    )
    assert (
        lead["reviewed_at"]
        == "2026-08-02 09:30:00"
    )
    assert (
        lead["review_notes"]
        == "Approved during Phase 6.1 migration."
    )
    assert (
        lead["outreach_approved_by_user_id"]
        == owner_id
    )
    assert (
        lead["outreach_approved_at"]
        == "2026-08-02 09:30:00"
    )

    assert db.execute(
        "SELECT COUNT(*) FROM leads"
    ).fetchone()[0] == 1
    assert db.execute(
        "PRAGMA quick_check"
    ).fetchone()[0] == "ok"
    assert db.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []
    db.close()


def test_invalid_research_status_is_rejected(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "invalid-status.db"
    monkeypatch.setattr(
        database,
        "DB_PATH",
        database_path,
    )
    _configure_owner(monkeypatch)
    database.init_db()

    db = _connect(database_path)
    owner_id = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner'
        """
    ).fetchone()["id"]

    quest_id = db.execute(
        """
        INSERT INTO tasks (
            user_id,
            title,
            description,
            status,
            quest_source,
            why
        )
        VALUES (
            ?,
            'Reject invalid research state',
            'Test the database constraint.',
            'backlog',
            'client_hunting',
            'Only supported states may be stored.'
        )
        """,
        (owner_id,),
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO leads (
                quest_id,
                request_fingerprint,
                dedupe_key,
                company,
                contact_person,
                source,
                problem_opportunity,
                why_mark_fits,
                next_action,
                research_status
            )
            VALUES (
                ?,
                'v1:invalid-research',
                'v1:invalid-research',
                'Invalid State Co',
                'Alex',
                'LinkedIn',
                'Needs reporting.',
                'Mark fits.',
                'Review.',
                'published'
            )
            """,
            (quest_id,),
        )
    db.close()
