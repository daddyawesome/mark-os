from __future__ import annotations

import sqlite3

import pytest

from app import database
from app.db import memory as memory_db
from app.services.agent_audit import create_agent_run
from app.services.chat import create_chat_session, save_chat_message
from app.services.memory import (
    accept_memory_candidate,
    archive_memory,
    archive_memory_candidate,
    create_memory_candidate,
    get_memory_candidate,
    reject_memory_candidate,
)
from app.services.personal_scope import user_scope
from app.services.team_users import create_lead_sourcer, create_member


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def memory_database(tmp_path, monkeypatch):
    database_path = tmp_path / "phase-8-1-memory.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = int(
            db.execute("SELECT id FROM users WHERE role = 'owner'").fetchone()[0]
        )
        member = create_member(
            db,
            username="member",
            display_name="Member",
            password="member-password-123",
            password_confirmation="member-password-123",
        )

    return database_path, owner_id, int(member["id"])


def _candidate(db, user_id: int, *, suffix: str = "one", request_key=None):
    return create_memory_candidate(
        db,
        user_id=user_id,
        memory_type="preference",
        memory_key="focus_style",
        memory_value=f"Protect one focused work block: {suffix}.",
        importance=8,
        source="phase_8_1_test",
        source_type="manual_test",
        source_id=1,
        confidence=0.9,
        sensitivity="private",
        candidate_reason="This preference should guide future planning.",
        request_key=request_key,
    )


def test_fresh_schema_has_phase_8_1_tables_indexes_and_triggers(memory_database):
    database_path, _, _ = memory_database
    database.init_db()

    db = sqlite3.connect(database_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    tables = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"memories", "memory_candidates", "memory_audit_events"} <= tables

    indexes = {
        row["name"]
        for table in ("memories", "memory_candidates", "memory_audit_events")
        for row in db.execute(f"PRAGMA index_list({table})").fetchall()
    }
    assert {
        memory_db.MEMORY_ACTIVE_KEY_INDEX,
        memory_db.MEMORY_VERSION_INDEX,
        memory_db.MEMORY_CANDIDATE_REQUEST_INDEX,
        memory_db.MEMORY_CANDIDATE_PENDING_HASH_INDEX,
        "idx_memory_candidates_user_status",
        "idx_memory_candidates_source",
        "idx_memory_audit_user_time",
        "idx_memory_audit_memory",
        "idx_memory_audit_candidate",
    } <= indexes

    active_index = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        (memory_db.MEMORY_ACTIVE_KEY_INDEX,),
    ).fetchone()["sql"]
    assert "where active = 1" in " ".join(active_index.lower().split())

    triggers = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    assert set(memory_db.TRIGGER_NAMES) <= triggers
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_candidate_state_constraints_reject_malformed_rows(memory_database):
    _, owner_id, _ = memory_database
    with database.get_db() as db:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            db.execute(
                """
                INSERT INTO memory_candidates (
                    user_id, memory_type, memory_key, memory_value, importance,
                    source, confidence, sensitivity, candidate_reason, status,
                    content_hash
                ) VALUES (?, 'preference', 'invalid', 'Invalid candidate.', 5,
                          'test', 1.0, 'normal', 'Invalid state.', 'accepted', ?)
                """,
                (owner_id, "a" * 64),
            )


def test_candidate_creation_is_idempotent_and_conflict_safe(memory_database):
    _, owner_id, _ = memory_database
    with database.get_db() as db:
        first = _candidate(db, owner_id, request_key="candidate-request-1")
        retry = _candidate(db, owner_id, request_key="candidate-request-1")
        same_content = _candidate(db, owner_id, request_key="candidate-request-2")

        assert first.created is True
        assert retry.duplicate is True
        assert same_content.duplicate is True
        assert retry.candidate["id"] == first.candidate["id"]
        assert same_content.candidate["id"] == first.candidate["id"]
        assert db.execute("SELECT COUNT(*) FROM memory_candidates").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM memory_audit_events").fetchone()[0] == 1

        with pytest.raises(ValueError, match="different memory candidate"):
            _candidate(
                db,
                owner_id,
                suffix="different",
                request_key="candidate-request-1",
            )


@pytest.mark.parametrize(
    "secret",
    (
        "password=hunter2",
        "Authorization: Bearer abcdefghijklmnop",
        "api_key=sk-example-secret-value",
        "-----BEGIN PRIVATE KEY----- secret",
        "Bank account number: 1234 5678 9012",
    ),
)
def test_candidates_reject_secrets_and_banking_information(
    memory_database,
    secret,
):
    _, owner_id, _ = memory_database
    with database.get_db() as db:
        with pytest.raises(ValueError, match="cannot be stored"):
            create_memory_candidate(
                db,
                user_id=owner_id,
                memory_type="preference",
                memory_key="unsafe",
                memory_value=secret,
                source="phase_8_1_test",
                candidate_reason="Test prohibited memory content.",
            )
        assert db.execute("SELECT COUNT(*) FROM memory_candidates").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM memory_audit_events").fetchone()[0] == 0


def test_acceptance_creates_versions_and_supersedes_once(memory_database):
    _, owner_id, _ = memory_database
    with database.get_db() as db:
        first_candidate = _candidate(db, owner_id, suffix="version one")
        first = accept_memory_candidate(
            db,
            int(first_candidate.candidate["id"]),
            user_id=owner_id,
        )
        event_count = db.execute(
            "SELECT COUNT(*) FROM memory_audit_events"
        ).fetchone()[0]
        retry = accept_memory_candidate(
            db,
            int(first_candidate.candidate["id"]),
            user_id=owner_id,
        )

        assert first.memory_created is True
        assert first.memory["version"] == 1
        assert first.memory["active"] == 1
        assert retry.memory_created is False
        assert retry.memory["id"] == first.memory["id"]
        assert db.execute("SELECT COUNT(*) FROM memory_audit_events").fetchone()[0] == event_count

        second_candidate = _candidate(db, owner_id, suffix="version two")
        second = accept_memory_candidate(
            db,
            int(second_candidate.candidate["id"]),
            user_id=owner_id,
        )
        old = db.execute(
            "SELECT * FROM memories WHERE id = ?",
            (first.memory["id"],),
        ).fetchone()

        assert second.memory["version"] == 2
        assert second.memory["active"] == 1
        assert second.superseded_memory_id == first.memory["id"]
        assert old["active"] == 0
        assert old["superseded_by"] == second.memory["id"]
        assert db.execute(
            """
            SELECT COUNT(*) FROM memories
            WHERE user_id = ? AND memory_key = 'focus_style' AND active = 1
            """,
            (owner_id,),
        ).fetchone()[0] == 1

        with pytest.raises(sqlite3.IntegrityError, match="referenced memory"):
            db.execute("DELETE FROM memories WHERE id = ?", (second.memory["id"],))

        archived = archive_memory(db, int(second.memory["id"]), user_id=owner_id)
        audit_count = db.execute(
            "SELECT COUNT(*) FROM memory_audit_events"
        ).fetchone()[0]
        assert archived["active"] == 0
        assert archive_memory(
            db,
            int(second.memory["id"]),
            user_id=owner_id,
        )["active"] == 0
        assert db.execute("SELECT COUNT(*) FROM memory_audit_events").fetchone()[0] == audit_count


def test_candidate_reject_and_archive_are_terminal_and_idempotent(memory_database):
    _, owner_id, _ = memory_database
    with database.get_db() as db:
        rejected_candidate = _candidate(db, owner_id, suffix="reject")
        rejected = reject_memory_candidate(
            db,
            int(rejected_candidate.candidate["id"]),
            reason="Not durable enough.",
            user_id=owner_id,
        )
        event_count = db.execute(
            "SELECT COUNT(*) FROM memory_audit_events"
        ).fetchone()[0]
        retry = reject_memory_candidate(
            db,
            int(rejected_candidate.candidate["id"]),
            reason="Not durable enough.",
            user_id=owner_id,
        )
        assert rejected["status"] == "rejected"
        assert retry["status"] == "rejected"
        assert db.execute("SELECT COUNT(*) FROM memory_audit_events").fetchone()[0] == event_count
        with pytest.raises(ValueError, match="Only pending"):
            accept_memory_candidate(
                db,
                int(rejected_candidate.candidate["id"]),
                user_id=owner_id,
            )

        archived_candidate = _candidate(db, owner_id, suffix="archive")
        archived = archive_memory_candidate(
            db,
            int(archived_candidate.candidate["id"]),
            reason="Duplicate planning detail.",
            user_id=owner_id,
        )
        assert archived["status"] == "archived"
        assert archive_memory_candidate(
            db,
            int(archived_candidate.candidate["id"]),
            reason="Duplicate planning detail.",
            user_id=owner_id,
        )["status"] == "archived"


def test_personal_isolation_and_agent_run_provenance(memory_database):
    _, owner_id, member_id = memory_database
    with database.get_db() as db:
        owner_candidate = _candidate(db, owner_id, suffix="owner only")
        assert get_memory_candidate(
            db,
            int(owner_candidate.candidate["id"]),
            user_id=member_id,
        ) is None
        with pytest.raises(ValueError, match="not found"):
            accept_memory_candidate(
                db,
                int(owner_candidate.candidate["id"]),
                user_id=member_id,
            )

        with user_scope(owner_id):
            session = create_chat_session(db, title="Memory source")
            message = save_chat_message(
                db,
                session_id=int(session["id"]),
                role="user",
                content="Remember my preference.",
                request_key="message-1",
            ).message
            run = create_agent_run(
                db,
                session_id=int(session["id"]),
                user_message_id=int(message["id"]),
                request_key="run-1",
            ).run

        with pytest.raises(ValueError, match="Agent run not found"):
            create_memory_candidate(
                db,
                user_id=member_id,
                memory_type="preference",
                memory_key="cross_user",
                memory_value="This must remain isolated.",
                source="agent",
                candidate_reason="Cross-user provenance must fail.",
                agent_run_id=int(run["id"]),
            )

        sourcer = create_lead_sourcer(
            db,
            username="sourcer",
            display_name="Sourcer",
            password="sourcer-password-123",
            password_confirmation="sourcer-password-123",
        )
        with pytest.raises(PermissionError, match="active owner or member"):
            _candidate(db, int(sourcer["id"]), suffix="not personal")


def test_audit_is_append_only_owner_checked_and_content_free(memory_database):
    _, owner_id, member_id = memory_database
    with database.get_db() as db:
        secret_free_value = "Protect a private focused block."
        result = create_memory_candidate(
            db,
            user_id=owner_id,
            memory_type="preference",
            memory_key="private_focus",
            memory_value=secret_free_value,
            source="phase_8_1_test",
            candidate_reason="Useful durable preference.",
        )
        event = db.execute("SELECT * FROM memory_audit_events").fetchone()
        assert secret_free_value not in event["details_json"]
        assert "private_focus" not in event["details_json"]

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(
                "UPDATE memory_audit_events SET source = 'changed' WHERE id = ?",
                (event["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM memory_audit_events WHERE id = ?", (event["id"],))
        with pytest.raises(sqlite3.IntegrityError, match="owner mismatch"):
            db.execute(
                """
                INSERT INTO memory_audit_events (
                    user_id, event_type, candidate_id, source
                ) VALUES (?, 'candidate_created', ?, 'forged')
                """,
                (member_id, result.candidate["id"]),
            )


def test_memory_lifecycle_does_not_change_quests_or_xp(memory_database):
    _, owner_id, _ = memory_database
    with database.get_db() as db:
        before = {
            "tasks": db.execute("SELECT * FROM tasks ORDER BY id").fetchall(),
            "xp": db.execute("SELECT * FROM xp_ledger ORDER BY id").fetchall(),
            "game": db.execute("SELECT * FROM game_state ORDER BY id").fetchall(),
        }
        candidate = _candidate(db, owner_id, suffix="no xp")
        accepted = accept_memory_candidate(
            db,
            int(candidate.candidate["id"]),
            user_id=owner_id,
        )
        archive_memory(db, int(accepted.memory["id"]), user_id=owner_id)

        assert db.execute("SELECT * FROM tasks ORDER BY id").fetchall() == before["tasks"]
        assert db.execute("SELECT * FROM xp_ledger ORDER BY id").fetchall() == before["xp"]
        assert db.execute("SELECT * FROM game_state ORDER BY id").fetchall() == before["game"]


def test_pre_phase_8_1_database_rehearsal_preserves_memory_rows(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "pre-phase-8-1-copy.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = int(
            db.execute("SELECT id FROM users WHERE role = 'owner'").fetchone()[0]
        )
        db.execute(
            """
            INSERT INTO memories (
                user_id, memory_type, memory_key, memory_value,
                importance, source, version
            ) VALUES (?, 'decision', 'preserve-me', 'Keep this row.', 9, 'legacy', 1)
            """,
            (owner_id,),
        )
        before = [
            tuple(row)
            for row in db.execute("SELECT * FROM memories ORDER BY id").fetchall()
        ]
        memory_db.drop_triggers(db)
        db.execute("DROP TABLE memory_audit_events")
        db.execute("DROP TABLE memory_candidates")
        db.execute(f"DROP INDEX {memory_db.MEMORY_VERSION_INDEX}")
        db.execute(f"DROP INDEX {memory_db.MEMORY_ACTIVE_KEY_INDEX}")
        db.execute(
            f"""
            CREATE UNIQUE INDEX {memory_db.MEMORY_ACTIVE_KEY_INDEX}
            ON memories(user_id, memory_key)
            """
        )

    database.init_db()
    database.init_db()

    with database.get_db() as db:
        after = [
            tuple(row)
            for row in db.execute("SELECT * FROM memories ORDER BY id").fetchall()
        ]
        assert after == before
        assert db.execute(
            "SELECT COUNT(*) FROM memories WHERE memory_key = 'preserve-me'"
        ).fetchone()[0] == 1
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_incompatible_partial_candidate_schema_fails_without_rewriting_data(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "partial-memory-candidate.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        memory_db.drop_triggers(db)
        db.execute("DROP TABLE memory_audit_events")
        db.execute("DROP TABLE memory_candidates")
        db.executescript(
            """
            CREATE TABLE memory_candidates (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                marker TEXT
            );
            INSERT INTO memory_candidates (id, marker)
            VALUES (17, 'preserve-me');
            """
        )

    with pytest.raises(RuntimeError, match="memory_candidates.*missing columns"):
        database.init_db()

    db = sqlite3.connect(database_path)
    assert db.execute(
        "SELECT id, marker FROM memory_candidates WHERE id = 17"
    ).fetchone() == (17, "preserve-me")
    db.close()


def test_candidate_and_audit_writes_rollback_with_outer_transaction(memory_database):
    _, owner_id, _ = memory_database
    db = sqlite3.connect(database.DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("BEGIN")
    _candidate(db, owner_id, suffix="rollback")
    db.rollback()
    assert db.execute("SELECT COUNT(*) FROM memory_candidates").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM memory_audit_events").fetchone()[0] == 0
    db.close()
