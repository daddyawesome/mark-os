from __future__ import annotations

import sqlite3

import pytest

from app import database


ACTIVITY_COLUMNS = [
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
]

EXPECTED_INDEXES = {
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


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _connect(path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _column_names(db: sqlite3.Connection, table_name: str) -> list[str]:
    return [
        row["name"]
        for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()
    ]


def _insert_quest(db: sqlite3.Connection, owner_id: int, title: str) -> int:
    columns = set(_column_names(db, "tasks"))
    if "user_id" in columns:
        return db.execute(
            """
            INSERT INTO tasks (
                user_id, title, description, status, quest_source, why
            )
            VALUES (?, ?, 'Lead activity migration test', 'backlog',
                    'client_hunting', 'Preserve CRM audit migration safety.')
            """,
            (owner_id, title),
        ).lastrowid
    return db.execute(
        """
        INSERT INTO tasks (title, description, status, quest_source, why)
        VALUES (?, 'Lead activity migration test', 'backlog',
                'client_hunting', 'Preserve CRM audit migration safety.')
        """,
        (title,),
    ).lastrowid


def _insert_lead(
    db: sqlite3.Connection,
    *,
    quest_id: int,
    owner_id: int,
    suffix: str,
) -> int:
    return db.execute(
        """
        INSERT INTO leads (
            organization_id,
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
            next_action
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'linkedin', ?, ?, ?)
        """,
        (
            db.execute(
                "SELECT id FROM organizations WHERE slug = 'mark-agency'"
            ).fetchone()[0],
            quest_id,
            owner_id,
            owner_id,
            f"phase-6-3a-request-{suffix}",
            f"phase-6-3a-fingerprint-{suffix}",
            f"phase-6-3a-dedupe-{suffix}",
            f"Phase 6.3A Company {suffix}",
            "Alex Buyer",
            "Manual reporting creates delayed decisions.",
            "Mark can automate the reporting workflow.",
            "Prepare a tailored introduction.",
        ),
    ).lastrowid


def _insert_activity(
    db: sqlite3.Connection,
    *,
    lead_id: int,
    owner_id: int,
    activity_type: str = "research_started",
    channel: str = "internal",
    response_status: str = "not_applicable",
    message_summary: str = "Research started for this lead.",
    corrected_by_user_id: int | None = None,
    correction_reason: str = "",
    deleted_at: str | None = None,
) -> int:
    return db.execute(
        """
        INSERT INTO lead_activities (
            lead_id,
            activity_type,
            activity_at,
            channel,
            message_summary,
            created_by_user_id,
            performed_by_user_id,
            responsible_user_id,
            response_status,
            next_follow_up_date,
            deleted_at,
            corrected_by_user_id,
            correction_reason
        )
        VALUES (
            ?, ?, '2026-08-06 13:00:00', ?, ?, ?, ?, ?, ?,
            '2026-08-08', ?, ?, ?
        )
        """,
        (
            lead_id,
            activity_type,
            channel,
            message_summary,
            owner_id,
            owner_id,
            owner_id,
            response_status,
            deleted_at,
            corrected_by_user_id,
            correction_reason,
        ),
    ).lastrowid


def _snapshot(db: sqlite3.Connection, table_name: str) -> list[tuple]:
    info = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    primary_key_columns = [
        row["name"] for row in sorted(info, key=lambda row: row["pk"])
        if row["pk"]
    ]
    if primary_key_columns:
        order_by = ", ".join(primary_key_columns)
    elif any(row["name"] == "id" for row in info):
        order_by = "id"
    else:
        order_by = "rowid"
    return [
        tuple(row)
        for row in db.execute(
            f"SELECT * FROM {table_name} ORDER BY {order_by}"
        ).fetchall()
    ]


def test_fresh_activity_schema_constraints_indexes_and_idempotence(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "phase-6-3a-fresh.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)

    database.init_db()
    database.init_db()

    db = _connect(path)
    assert _column_names(db, "lead_activities") == ACTIVITY_COLUMNS

    columns = {
        row["name"]: row
        for row in db.execute(
            "PRAGMA table_info(lead_activities)"
        ).fetchall()
    }
    assert columns["channel"]["dflt_value"] == "'internal'"
    assert columns["notes"]["dflt_value"] == "''"
    assert columns["response_status"]["dflt_value"] == "'not_applicable'"
    assert columns["created_at"]["dflt_value"] == "CURRENT_TIMESTAMP"
    assert columns["updated_at"]["dflt_value"] == "CURRENT_TIMESTAMP"
    assert columns["correction_reason"]["dflt_value"] == "''"

    index_rows = {
        row["name"]: row
        for row in db.execute(
            "PRAGMA index_list(lead_activities)"
        ).fetchall()
    }
    for index_name, expected_columns in EXPECTED_INDEXES.items():
        index = index_rows[index_name]
        assert not bool(index["unique"])
        assert not bool(index["partial"])
        assert [
            row["name"]
            for row in db.execute(
                f"PRAGMA index_info({index_name})"
            ).fetchall()
        ] == expected_columns

    foreign_keys = {
        (row["table"], row["from"], row["to"], row["on_delete"])
        for row in db.execute(
            "PRAGMA foreign_key_list(lead_activities)"
        ).fetchall()
    }
    assert foreign_keys == {
        ("leads", "lead_id", "id", "RESTRICT"),
        ("users", "created_by_user_id", "id", "RESTRICT"),
        ("users", "performed_by_user_id", "id", "RESTRICT"),
        ("users", "responsible_user_id", "id", "RESTRICT"),
        ("users", "corrected_by_user_id", "id", "RESTRICT"),
    }

    owner_id = db.execute(
        "SELECT id FROM users WHERE role = 'owner' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    quest_id = _insert_quest(db, owner_id, "Verify activity schema")
    lead_id = _insert_lead(
        db,
        quest_id=quest_id,
        owner_id=owner_id,
        suffix="fresh",
    )
    activity_id = _insert_activity(
        db,
        lead_id=lead_id,
        owner_id=owner_id,
    )
    activity = db.execute(
        "SELECT * FROM lead_activities WHERE id = ?",
        (activity_id,),
    ).fetchone()
    assert activity["notes"] == ""
    assert activity["response_status"] == "not_applicable"
    assert activity["deleted_at"] is None
    assert activity["corrected_by_user_id"] is None
    assert activity["correction_reason"] == ""

    invalid_values = (
        {"activity_type": "unknown_activity"},
        {"channel": "sms"},
        {"response_status": "maybe"},
        {"message_summary": "   "},
    )
    for changes in invalid_values:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_activity(
                db,
                lead_id=lead_id,
                owner_id=owner_id,
                **changes,
            )

    with pytest.raises(sqlite3.IntegrityError):
        _insert_activity(
            db,
            lead_id=lead_id,
            owner_id=owner_id,
            corrected_by_user_id=owner_id,
            correction_reason="",
        )
    with pytest.raises(sqlite3.IntegrityError):
        _insert_activity(
            db,
            lead_id=lead_id,
            owner_id=owner_id,
            correction_reason="Reason without a correcting actor.",
        )
    with pytest.raises(sqlite3.IntegrityError):
        _insert_activity(
            db,
            lead_id=lead_id,
            owner_id=owner_id,
            deleted_at="2026-08-06 14:00:00",
        )
    with pytest.raises(sqlite3.IntegrityError):
        _insert_activity(
            db,
            lead_id=999999,
            owner_id=owner_id,
        )

    corrected_id = _insert_activity(
        db,
        lead_id=lead_id,
        owner_id=owner_id,
        corrected_by_user_id=owner_id,
        correction_reason="Corrected an inaccurate research timestamp.",
        deleted_at="2026-08-06 14:00:00",
    )
    assert corrected_id > activity_id
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_previous_database_adds_activity_table_without_changing_existing_data(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "phase-6-3a-legacy.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    db = _connect(path)
    owner_id = db.execute(
        "SELECT id FROM users WHERE role = 'owner' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    quest_id = _insert_quest(db, owner_id, "Preserve legacy CRM records")
    lead_id = _insert_lead(
        db,
        quest_id=quest_id,
        owner_id=owner_id,
        suffix="legacy",
    )
    db.execute(
        """
        UPDATE leads
        SET researched_by_user_id = ?,
            research_status = 'approved',
            reviewed_by_user_id = ?,
            reviewed_at = '2026-08-05 09:00:00',
            review_notes = 'Preserve approved research.',
            outreach_approved_by_user_id = ?,
            outreach_approved_at = '2026-08-05 09:30:00',
            business_development_owner_user_id = ?
        WHERE id = ?
        """,
        (owner_id, owner_id, owner_id, owner_id, lead_id),
    )

    xp_columns = set(_column_names(db, "xp_ledger"))
    if "user_id" in xp_columns:
        db.execute(
            """
            INSERT INTO xp_ledger (
                user_id, task_id, event_key, event_type, source_type,
                source_id, source_title, xp_delta, level_before,
                level_after, reason
            )
            VALUES (?, ?, ?, 'quest_completed', 'quest', ?, ?, 25, 3, 3, ?)
            """,
            (
                owner_id,
                quest_id,
                f"quest_completed:{quest_id}",
                quest_id,
                "Preserve legacy CRM records",
                "Phase 6.3A must not alter XP.",
            ),
        )
    else:
        db.execute(
            """
            INSERT INTO xp_ledger (
                task_id, event_key, event_type, source_type, source_id,
                source_title, xp_delta, level_before, level_after, reason
            )
            VALUES (?, ?, 'quest_completed', 'quest', ?, ?, 25, 3, 3, ?)
            """,
            (
                quest_id,
                f"quest_completed:{quest_id}",
                quest_id,
                "Preserve legacy CRM records",
                "Phase 6.3A must not alter XP.",
            ),
        )

    timeline_columns = set(_column_names(db, "timeline_events"))
    if "user_id" in timeline_columns:
        db.execute(
            """
            INSERT INTO timeline_events (
                user_id, event_date, event_type, title, summary, source
            )
            VALUES (?, '2026-08-05', 'legacy_record',
                    'Preserve timeline', 'Legacy timeline data.', 'test')
            """,
            (owner_id,),
        )
    else:
        db.execute(
            """
            INSERT INTO timeline_events (
                event_date, event_type, title, summary, source
            )
            VALUES ('2026-08-05', 'legacy_record',
                    'Preserve timeline', 'Legacy timeline data.', 'test')
            """
        )

    playbook_id = db.execute(
        """
        INSERT INTO playbooks (
            slug, title, markdown_content, created_by_user_id
        )
        VALUES ('phase-6-3a-legacy', 'Legacy Playbook',
                '# Preserve this playbook', ?)
        """,
        (owner_id,),
    ).lastrowid
    db.execute(
        """
        INSERT INTO user_playbook_assignments (user_id, playbook_id)
        VALUES (?, ?)
        """,
        (owner_id, playbook_id),
    )
    db.commit()

    protected_tables = (
        "users",
        "tasks",
        "xp_ledger",
        "timeline_events",
        "leads",
        "playbooks",
        "user_playbook_assignments",
    )
    before = {
        table_name: _snapshot(db, table_name)
        for table_name in protected_tables
    }
    db.execute("DROP TABLE lead_activities")
    db.commit()
    db.close()

    database.init_db()
    database.init_db()

    db = _connect(path)
    after = {
        table_name: _snapshot(db, table_name)
        for table_name in protected_tables
    }
    assert after == before
    assert _column_names(db, "lead_activities") == ACTIVITY_COLUMNS
    assert set(EXPECTED_INDEXES).issubset(
        {
            row["name"]
            for row in db.execute(
                "PRAGMA index_list(lead_activities)"
            ).fetchall()
        }
    )
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_partial_activity_schema_fails_closed_without_rewriting_rows(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "phase-6-3a-partial.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    db = _connect(path)
    db.execute("DROP TABLE lead_activities")
    db.executescript(
        """
        CREATE TABLE lead_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL
        );
        INSERT INTO lead_activities (id, lead_id) VALUES (17, 999999);
        """
    )
    db.commit()
    db.close()

    with pytest.raises(
        RuntimeError,
        match="Incompatible lead activity schema",
    ):
        database.init_db()

    db = _connect(path)
    partial_row = db.execute(
        "SELECT id, lead_id FROM lead_activities WHERE id = 17"
    ).fetchone()
    assert tuple(partial_row) == (17, 999999)
    assert _column_names(db, "lead_activities") == ["id", "lead_id"]
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


def test_wrong_existing_activity_index_fails_validation(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "phase-6-3a-index.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    db = _connect(path)
    db.execute("DROP INDEX idx_lead_activities_lead_timeline")
    db.execute(
        """
        CREATE INDEX idx_lead_activities_lead_timeline
        ON lead_activities(activity_at, lead_id)
        """
    )
    db.commit()
    db.close()

    with pytest.raises(
        RuntimeError,
        match="Incompatible lead activity index",
    ):
        database.init_db()

    db = _connect(path)
    assert [
        row["name"]
        for row in db.execute(
            "PRAGMA index_info(idx_lead_activities_lead_timeline)"
        ).fetchall()
    ] == ["activity_at", "lead_id"]
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()
