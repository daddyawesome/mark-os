import sqlite3

import pytest

from app import database
from app.services.lead_identity import lead_creation_fingerprint


LEAD_COLUMNS = [
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
]

EXPECTED_LEAD_INDEXES = {
    "idx_leads_quest_id": (
        True,
        False,
        ["quest_id"],
    ),
    "idx_leads_active_dedupe_key": (
        True,
        True,
        ["dedupe_key"],
    ),
    "idx_leads_request_key": (
        True,
        True,
        ["request_key"],
    ),
    "idx_leads_pipeline_priority_activity": (
        False,
        False,
        ["deleted_at", "pipeline_status", "priority", "updated_at", "id"],
    ),
    "idx_leads_due_action": (
        False,
        False,
        ["deleted_at", "next_action_due_date", "id"],
    ),
    "idx_leads_creator_activity": (
        False,
        False,
        ["created_by_user_id", "deleted_at", "updated_at", "id"],
    ),
    "idx_leads_assignee_pipeline": (
        False,
        False,
        ["assigned_to_user_id", "deleted_at", "pipeline_status", "id"],
    ),
}

PROTECTED_TABLES = (
    "tasks",
    "xp_ledger",
    "checkins",
    "memories",
    "chat_sessions",
    "chat_messages",
    "agent_runs",
    "agent_steps",
)


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


def _index_names(db: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }


def _column_names(db: sqlite3.Connection, table_name: str) -> list[str]:
    return [row[1] for row in db.execute(f"PRAGMA table_info({table_name})")]


def _index_details(
    db: sqlite3.Connection,
    index_name: str,
) -> tuple[bool, bool, list[str]]:
    indexes = {
        row[1]: row for row in db.execute("PRAGMA index_list(leads)").fetchall()
    }
    index = indexes[index_name]
    columns = [
        row[2] for row in db.execute(f"PRAGMA index_info({index_name})").fetchall()
    ]
    return bool(index[2]), bool(index[4]), columns


def _normalized_index_sql(db: sqlite3.Connection, index_name: str) -> str:
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index_name,),
    ).fetchone()
    assert row is not None and row[0] is not None
    return " ".join(row[0].lower().split()).rstrip(";")


def _insert_quest(db: sqlite3.Connection, title: str) -> int:
    return db.execute(
        """
        INSERT INTO tasks (title, description, status, quest_source, why)
        VALUES (?, 'CRM migration test', 'backlog', 'client_hunting',
                'Protect the existing Quest Engine while testing lead linkage.')
        """,
        (title,),
    ).lastrowid


def _insert_lead(
    db: sqlite3.Connection,
    *,
    quest_id: int,
    dedupe_key: str,
    request_key: str | None,
    request_fingerprint: str | None = None,
    company: str = "Acme Analytics",
    contact_person: str = "Alex Buyer",
    source: str = "linkedin",
    problem_opportunity: str = "Manual weekly reporting",
    why_mark_fits: str = "Power BI and automation experience",
    next_action: str = "Send a tailored introduction",
    pipeline_status: str = "new",
    priority: str = "medium",
    deleted_at: str | None = None,
) -> int:
    common_values = (
        quest_id,
        request_key,
        dedupe_key,
        company,
        contact_person,
        source,
        problem_opportunity,
        why_mark_fits,
        pipeline_status,
        priority,
        next_action,
        deleted_at,
    )
    if "request_fingerprint" not in _column_names(db, "leads"):
        return db.execute(
            """
            INSERT INTO leads
                (quest_id, request_key, dedupe_key, company, contact_person,
                 source, problem_opportunity, why_mark_fits, pipeline_status,
                 priority, next_action, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            common_values,
        ).lastrowid

    return db.execute(
        """
        INSERT INTO leads
            (quest_id, request_key, request_fingerprint, dedupe_key,
             company, contact_person, source, problem_opportunity,
             why_mark_fits, pipeline_status, priority, next_action, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            quest_id,
            request_key,
            request_fingerprint or f"fingerprint:{dedupe_key}",
            *common_values[2:],
        ),
    ).lastrowid


def _replace_with_prior_crm_table(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        DROP TABLE leads;

        CREATE TABLE leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quest_id INTEGER NOT NULL,
            request_key TEXT,
            dedupe_key TEXT NOT NULL CHECK(length(trim(dedupe_key)) > 0),
            company TEXT NOT NULL CHECK(length(trim(company)) > 0),
            contact_person TEXT NOT NULL CHECK(length(trim(contact_person)) > 0),
            job_title TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL CHECK(length(trim(source)) > 0),
            source_url TEXT NOT NULL DEFAULT '',
            problem_opportunity TEXT NOT NULL
                CHECK(length(trim(problem_opportunity)) > 0),
            why_mark_fits TEXT NOT NULL CHECK(length(trim(why_mark_fits)) > 0),
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


def _snapshot(db: sqlite3.Connection, table_name: str) -> list[tuple]:
    return [
        tuple(row)
        for row in db.execute(f"SELECT * FROM {table_name} ORDER BY id").fetchall()
    ]


def _populate_current_database(db: sqlite3.Connection) -> None:
    quest_id = _insert_quest(db, "Preserve current CRM-predecessor quest")
    db.execute(
        """
        INSERT INTO xp_ledger
            (task_id, event_key, event_type, source_type, source_id,
             source_title, xp_delta, level_before, level_after, reason)
        VALUES
            (?, ?, 'quest_completed', 'quest', ?, ?, 25, 3, 3, ?)
        """,
        (
            quest_id,
            f"quest_completed:{quest_id}",
            quest_id,
            "Preserve current CRM-predecessor quest",
            "Legacy XP must remain unchanged",
        ),
    )
    db.execute(
        """
        INSERT INTO checkins
            (checkin_date, cash, cash_in, expenses, free_hours, energy,
             accomplished, blocker, notes, created_at, updated_at)
        VALUES
            ('2026-08-03', 1000, 100, 25, 2, 4, 'Protected work', '',
             'Pre-CRM check-in', '2026-08-03 08:00:00',
             '2026-08-03 08:05:00')
        """
    )
    db.execute(
        """
        INSERT INTO memories
            (memory_type, memory_key, memory_value, importance, source,
             active, created_at, updated_at)
        VALUES
            ('lesson', 'pre_crm_preservation', 'Keep existing records', 8,
             'test', 1, '2026-08-03 08:00:00', '2026-08-03 08:00:00')
        """
    )
    session_id = db.execute(
        """
        INSERT INTO chat_sessions
            (title, status, created_at, updated_at, last_message_at)
        VALUES
            ('Pre-CRM chat', 'active', '2026-08-03 09:00:00',
             '2026-08-03 09:01:00', '2026-08-03 09:01:00')
        """
    ).lastrowid
    message_id = db.execute(
        """
        INSERT INTO chat_messages
            (session_id, role, content, request_key, created_at, updated_at)
        VALUES
            (?, 'user', 'Preserve this message', 'pre-crm-message',
             '2026-08-03 09:01:00', '2026-08-03 09:01:00')
        """,
        (session_id,),
    ).lastrowid
    run_id = db.execute(
        """
        INSERT INTO agent_runs
            (session_id, user_message_id, request_key, intent, status,
             loop_selected, step_count, tool_call_count, started_at,
             completed_at, created_at, updated_at)
        VALUES
            (?, ?, 'pre-crm-run', 'quest_update', 'completed', 'quest_loop',
             1, 1, '2026-08-03 09:01:00', '2026-08-03 09:01:01',
             '2026-08-03 09:01:00', '2026-08-03 09:01:01')
        """,
        (session_id, message_id),
    ).lastrowid
    db.execute(
        """
        INSERT INTO agent_steps
            (run_id, step_number, step_key, step_type, name, status,
             tool_name, started_at, completed_at, created_at, updated_at)
        VALUES
            (?, 1, 'pre-crm-step', 'tool_call', 'update_quest', 'completed',
             'quest_service', '2026-08-03 09:01:00',
             '2026-08-03 09:01:01', '2026-08-03 09:01:00',
             '2026-08-03 09:01:01')
        """,
        (run_id,),
    )


def test_fresh_database_has_exact_crm_schema_constraints_indexes_and_fk(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "fresh-crm.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    assert "leads" in _table_names(db)
    assert _column_names(db, "leads") == LEAD_COLUMNS
    for index_name, expected in EXPECTED_LEAD_INDEXES.items():
        assert _index_details(db, index_name) == expected

    dedupe_sql = _normalized_index_sql(db, "idx_leads_active_dedupe_key")
    _, separator, predicate = dedupe_sql.partition(" where ")
    assert separator and predicate == "deleted_at is null"
    request_sql = _normalized_index_sql(db, "idx_leads_request_key")
    _, separator, predicate = request_sql.partition(" where ")
    assert separator and predicate == "request_key is not null"

    foreign_keys = db.execute("PRAGMA foreign_key_list(leads)").fetchall()
    assert {
        (row[2], row[3], row[4], row[6]) for row in foreign_keys
    } == {("tasks", "quest_id", "id", "RESTRICT")}

    columns = {
        row[1]: row for row in db.execute("PRAGMA table_info(leads)").fetchall()
    }
    assert columns["job_title"][4] == "''"
    assert columns["source_url"][4] == "''"
    assert columns["notes"][4] == "''"
    assert columns["pipeline_status"][4] == "'new'"
    assert columns["priority"][4] == "'medium'"
    assert columns["created_at"][4] == "CURRENT_TIMESTAMP"
    assert columns["updated_at"][4] == "CURRENT_TIMESTAMP"

    quest_id = _insert_quest(db, "Contact Acme Analytics")
    lead_id = _insert_lead(
        db,
        quest_id=quest_id,
        dedupe_key="v1:acme-alex",
        request_key="lead-request-1",
    )
    lead_defaults = db.execute(
        """
        SELECT
            job_title,
            source_url,
            pipeline_status,
            priority,
            notes
        FROM leads
        WHERE id = ?
        """,
        (lead_id,),
    ).fetchone()
    assert lead_defaults == ("", "", "new", "medium", "")

    with pytest.raises(sqlite3.IntegrityError):
        _insert_lead(
            db,
            quest_id=_insert_quest(db, "Invalid pipeline quest"),
            dedupe_key="v1:invalid-pipeline",
            request_key="invalid-pipeline",
            pipeline_status="nurturing",
        )
    with pytest.raises(sqlite3.IntegrityError):
        _insert_lead(
            db,
            quest_id=_insert_quest(db, "Invalid priority quest"),
            dedupe_key="v1:invalid-priority",
            request_key="invalid-priority",
            priority="urgent",
        )

    for column_name in (
        "dedupe_key",
        "request_fingerprint",
        "company",
        "contact_person",
        "source",
        "problem_opportunity",
        "why_mark_fits",
        "next_action",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                f"UPDATE leads SET {column_name} = '   ' WHERE id = ?",
                (lead_id,),
            )

    second_quest_id = _insert_quest(db, "Second Acme outreach")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_lead(
            db,
            quest_id=second_quest_id,
            dedupe_key="v1:acme-alex",
            request_key="lead-request-2",
        )

    db.execute(
        "UPDATE leads SET deleted_at = '2026-08-03 12:00:00' WHERE id = ?",
        (lead_id,),
    )
    replacement_id = _insert_lead(
        db,
        quest_id=second_quest_id,
        dedupe_key="v1:acme-alex",
        request_key="lead-request-2",
    )
    assert replacement_id != lead_id

    third_quest_id = _insert_quest(db, "Third Acme outreach")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_lead(
            db,
            quest_id=third_quest_id,
            dedupe_key="v1:another-lead",
            request_key="lead-request-1",
        )
    with pytest.raises(sqlite3.IntegrityError):
        _insert_lead(
            db,
            quest_id=quest_id,
            dedupe_key="v1:another-identity",
            request_key="lead-request-3",
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM tasks WHERE id = ?", (quest_id,))

    with pytest.raises(sqlite3.IntegrityError):
        _insert_lead(
            db,
            quest_id=999999,
            dedupe_key="v1:orphan",
            request_key="orphan-request",
        )

    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_prior_crm_schema_adds_and_backfills_request_fingerprint(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "prior-crm-fingerprint.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = _connect(database_path)
    _replace_with_prior_crm_table(db)
    quest_id = _insert_quest(db, "Preserve prior CRM lead")
    lead_id = _insert_lead(
        db,
        quest_id=quest_id,
        dedupe_key="v1:prior-crm-lead",
        request_key="prior-crm-request",
    )
    db.commit()
    db.close()

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    db.row_factory = sqlite3.Row
    migrated_columns = _column_names(db, "leads")
    assert set(migrated_columns) == set(LEAD_COLUMNS)
    assert "request_fingerprint" in migrated_columns
    assert "created_by_user_id" in migrated_columns
    assert "assigned_to_user_id" in migrated_columns
    lead = db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    expected_values = {
        "dedupe_key": "v1:prior-crm-lead",
        "company": "Acme Analytics",
        "contact_person": "Alex Buyer",
        "job_title": "",
        "source": "linkedin",
        "source_url": "",
        "problem_opportunity": "Manual weekly reporting",
        "why_mark_fits": "Power BI and automation experience",
        "pipeline_status": "new",
        "priority": "medium",
        "next_action": "Send a tailored introduction",
        "next_action_due_date": None,
        "notes": "",
    }
    assert lead["request_fingerprint"] == lead_creation_fingerprint(expected_values)
    assert lead["request_fingerprint"] != "migration-backfill-required"
    assert lead["quest_id"] == quest_id
    assert db.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1
    for index_name, expected in EXPECTED_LEAD_INDEXES.items():
        assert _index_details(db, index_name) == expected
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_prior_crm_fingerprint_migration_rolls_back_and_retries_after_failure(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "prior-crm-fingerprint-failure.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = _connect(database_path)
    _replace_with_prior_crm_table(db)
    quest_id = _insert_quest(db, "Retry prior CRM migration")
    lead_id = _insert_lead(
        db,
        quest_id=quest_id,
        dedupe_key="v1:retry-prior-crm",
        request_key="retry-prior-crm",
    )
    db.executescript(
        """
        CREATE TRIGGER reject_crm_fingerprint_backfill
        BEFORE UPDATE ON leads
        BEGIN
            SELECT RAISE(ABORT, 'test fingerprint backfill failure');
        END;
        """
    )
    db.commit()
    db.close()

    with pytest.raises(sqlite3.IntegrityError, match="backfill failure"):
        database.init_db()

    db = _connect(database_path)
    assert "request_fingerprint" not in _column_names(db, "leads")
    assert db.execute("SELECT COUNT(*) FROM leads WHERE id = ?", (lead_id,)).fetchone()[
        0
    ] == 1
    db.execute("DROP TRIGGER reject_crm_fingerprint_backfill")
    db.commit()
    db.close()

    database.init_db()

    db = _connect(database_path)
    fingerprint = db.execute(
        "SELECT request_fingerprint FROM leads WHERE id = ?",
        (lead_id,),
    ).fetchone()[0]
    assert fingerprint.startswith("v1:")
    assert fingerprint != database.CRM_FINGERPRINT_BACKFILL_SENTINEL
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


def test_existing_fingerprint_sentinel_is_resumed_on_startup(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "prior-crm-fingerprint-resume.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = _connect(database_path)
    _replace_with_prior_crm_table(db)
    quest_id = _insert_quest(db, "Resume prior CRM migration")
    lead_id = _insert_lead(
        db,
        quest_id=quest_id,
        dedupe_key="v1:resume-prior-crm",
        request_key="resume-prior-crm",
    )
    db.execute(
        f"""
        ALTER TABLE leads
        ADD COLUMN request_fingerprint TEXT NOT NULL
            DEFAULT '{database.CRM_FINGERPRINT_BACKFILL_SENTINEL}'
            CHECK(length(trim(request_fingerprint)) > 0)
        """
    )
    db.commit()
    assert db.execute(
        "SELECT request_fingerprint FROM leads WHERE id = ?",
        (lead_id,),
    ).fetchone()[0] == database.CRM_FINGERPRINT_BACKFILL_SENTINEL
    db.close()

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    fingerprint = db.execute(
        "SELECT request_fingerprint FROM leads WHERE id = ?",
        (lead_id,),
    ).fetchone()[0]
    assert fingerprint.startswith("v1:")
    assert fingerprint != database.CRM_FINGERPRINT_BACKFILL_SENTINEL
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_pre_crm_current_database_upgrades_without_data_loss(tmp_path, monkeypatch):
    database_path = tmp_path / "pre-crm-current.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = _connect(database_path)
    _populate_current_database(db)
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0
    db.execute("DROP TABLE leads")
    db.commit()
    assert "leads" not in _table_names(db)
    before = {table: _snapshot(db, table) for table in PROTECTED_TABLES}
    db.close()

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    after = {table: _snapshot(db, table) for table in PROTECTED_TABLES}
    assert after == before
    assert "leads" in _table_names(db)
    assert db.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0
    assert set(EXPECTED_LEAD_INDEXES).issubset(_index_names(db))
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_incompatible_partial_crm_schema_fails_without_data_loss(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "partial-crm.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = _connect(database_path)
    db.execute("DROP TABLE leads")
    db.executescript(
        """
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL
        );
        INSERT INTO leads (id, company) VALUES (17, 'Preserve partial lead');
        """
    )
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="Incompatible leads schema"):
        database.init_db()

    db = _connect(database_path)
    assert db.execute("SELECT * FROM leads WHERE id = 17").fetchone() == (
        17,
        "Preserve partial lead",
    )
    assert not set(EXPECTED_LEAD_INDEXES).intersection(_index_names(db))
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


def test_orphaned_lead_quest_reference_fails_without_data_loss(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "orphaned-lead.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = sqlite3.connect(database_path)
    db.execute("PRAGMA foreign_keys = OFF")
    orphan_id = _insert_lead(
        db,
        quest_id=999999,
        dedupe_key="v1:orphaned-existing-lead",
        request_key="orphaned-existing-lead",
    )
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="orphaned quest references"):
        database.init_db()

    db = sqlite3.connect(database_path)
    assert db.execute(
        "SELECT quest_id FROM leads WHERE id = ?", (orphan_id,)
    ).fetchone() == (999999,)
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


@pytest.mark.parametrize(
    ("index_name", "replacement_sql"),
    [
        (
            "idx_leads_quest_id",
            "CREATE INDEX idx_leads_quest_id ON leads(quest_id)",
        ),
        (
            "idx_leads_active_dedupe_key",
            """
            CREATE UNIQUE INDEX idx_leads_active_dedupe_key
            ON leads(dedupe_key)
            WHERE deleted_at IS NULL AND pipeline_status = 'new'
            """,
        ),
        (
            "idx_leads_pipeline_priority_activity",
            """
            CREATE INDEX idx_leads_pipeline_priority_activity
            ON leads(pipeline_status, priority, updated_at, id)
            """,
        ),
        (
            "idx_leads_due_action",
            """
            CREATE INDEX idx_leads_due_action
            ON leads(deleted_at, next_action_due_date, id)
            WHERE next_action_due_date IS NOT NULL
            """,
        ),
    ],
)
def test_wrong_existing_crm_index_fails_validation(
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

    with pytest.raises(RuntimeError, match="CRM index"):
        database.init_db()

    db = _connect(database_path)
    assert index_name in _index_names(db)
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


@pytest.mark.parametrize("duplicate_kind", ["quest", "dedupe", "request"])
def test_duplicate_crm_rows_fail_unique_index_migration_without_data_loss(
    tmp_path,
    monkeypatch,
    duplicate_kind,
):
    database_path = tmp_path / f"duplicate-{duplicate_kind}.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = _connect(database_path)
    first_quest_id = _insert_quest(db, f"First {duplicate_kind} quest")
    second_quest_id = _insert_quest(db, f"Second {duplicate_kind} quest")
    index_name = {
        "quest": "idx_leads_quest_id",
        "dedupe": "idx_leads_active_dedupe_key",
        "request": "idx_leads_request_key",
    }[duplicate_kind]
    db.execute(f"DROP INDEX {index_name}")

    first_values = {
        "quest_id": first_quest_id,
        "dedupe_key": "v1:first",
        "request_key": "first-request",
    }
    second_values = {
        "quest_id": second_quest_id,
        "dedupe_key": "v1:second",
        "request_key": "second-request",
    }
    if duplicate_kind == "quest":
        second_values["quest_id"] = first_quest_id
    elif duplicate_kind == "dedupe":
        second_values["dedupe_key"] = first_values["dedupe_key"]
    else:
        second_values["request_key"] = first_values["request_key"]

    _insert_lead(db, **first_values)
    _insert_lead(db, **second_values)
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="CRM link or duplicate protection"):
        database.init_db()

    db = _connect(database_path)
    assert db.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 2
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()
