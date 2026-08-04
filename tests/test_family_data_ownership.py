from __future__ import annotations

import sqlite3

from app import database
from app.db import family_ownership
from app.services.team_users import create_member


PERSONAL_TABLES = (
    "profile",
    "goals",
    "projects",
    "checkins",
    "directions",
    "game_state",
    "game_history",
    "tasks",
    "quest_updates",
    "xp_ledger",
    "memories",
    "timeline_events",
    "chat_sessions",
    "chat_messages",
    "agent_runs",
    "agent_steps",
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _connect(path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _row_counts(db: sqlite3.Connection) -> dict[str, int]:
    return {
        table_name: int(
            db.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()[0]
        )
        for table_name in PERSONAL_TABLES
    }


def _row_ids(db: sqlite3.Connection) -> dict[str, list[int]]:
    return {
        table_name: [
            int(row["id"])
            for row in db.execute(
                f"SELECT id FROM {table_name} ORDER BY id"
            ).fetchall()
        ]
        for table_name in PERSONAL_TABLES
    }


def test_m8_backfills_all_existing_personal_rows_to_owner(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "family-ownership.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    owner_id = family_ownership.get_owner_id(db)

    for table_name in PERSONAL_TABLES:
        columns = {
            row["name"]: row
            for row in db.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()
        }
        assert "user_id" in columns
        assert columns["user_id"]["type"].upper() == "INTEGER"
        assert db.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE user_id IS NULL
            """
        ).fetchone()[0] == 0
        assert db.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE user_id != ?
            """,
            (owner_id,),
        ).fetchone()[0] == 0

    assert "user_id" not in {
        row["name"]
        for row in db.execute(
            "PRAGMA table_info(system_meta)"
        ).fetchall()
    }
    db.close()


def test_m8_is_idempotent_and_preserves_ids_and_counts(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "family-ownership-repeat.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)

    database.init_db()
    first = _connect(database_path)
    before_counts = _row_counts(first)
    before_ids = _row_ids(first)
    first.close()

    database.init_db()
    database.init_db()

    second = _connect(database_path)
    assert _row_counts(second) == before_counts
    assert _row_ids(second) == before_ids
    assert second.execute(
        "PRAGMA quick_check"
    ).fetchone()[0] == "ok"
    assert second.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []
    second.close()


def test_member_starts_with_blank_workspace(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "member-empty.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)

    database.init_db()

    with database.get_db() as db:
        member = create_member(
            db,
            username="wife",
            display_name="Wife",
            password="family-pass-123",
            password_confirmation="family-pass-123",
        )

    database.init_db()

    db = _connect(database_path)
    member_id = int(member["id"])
    assert db.execute(
        "SELECT COUNT(*) FROM profile WHERE user_id = ?",
        (member_id,),
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM game_state WHERE user_id = ?",
        (member_id,),
    ).fetchone()[0] == 1

    for table_name in PERSONAL_TABLES:
        expected = 1 if table_name in {"profile", "game_state"} else 0
        assert db.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE user_id = ?
            """,
            (member_id,),
        ).fetchone()[0] == expected
    db.close()


def test_profile_and_game_state_are_no_longer_singletons(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "family-singletons.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)

    database.init_db()

    db = _connect(database_path)
    profile_sql = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'profile'
        """
    ).fetchone()["sql"].lower()
    game_state_sql = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'game_state'
        """
    ).fetchone()["sql"].lower()

    assert "check (id = 1)" not in profile_sql
    assert "check(id = 1)" not in profile_sql
    assert "check (id = 1)" not in game_state_sql
    assert "check(id = 1)" not in game_state_sql

    profile_indexes = db.execute(
        "PRAGMA index_list(profile)"
    ).fetchall()
    game_indexes = db.execute(
        "PRAGMA index_list(game_state)"
    ).fetchall()

    assert any(row["unique"] for row in profile_indexes)
    assert any(row["unique"] for row in game_indexes)
    db.close()


def test_m8_does_not_change_crm_ownership_columns(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "crm-boundary.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)

    database.init_db()

    db = _connect(database_path)
    lead_columns = {
        row["name"]
        for row in db.execute(
            "PRAGMA table_info(leads)"
        ).fetchall()
    }

    assert "created_by_user_id" in lead_columns
    assert "assigned_to_user_id" in lead_columns
    assert "user_id" not in lead_columns
    db.close()
