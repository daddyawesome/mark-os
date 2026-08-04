from __future__ import annotations

import sqlite3

from app import database
from app.services.passwords import (
    hash_password,
    needs_rehash,
    verify_password,
)


USER_COLUMNS = {
    "id",
    "username",
    "display_name",
    "password_hash",
    "role",
    "active",
    "must_change_password",
    "last_login_at",
    "created_at",
    "updated_at",
}


def _connect(database_path) -> sqlite3.Connection:
    db = sqlite3.connect(database_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def test_password_hash_round_trip_uses_random_salts():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first != second
    assert "correct horse battery staple" not in first
    assert verify_password("correct horse battery staple", first)
    assert verify_password("correct horse battery staple", second)
    assert not verify_password("wrong password", first)
    assert not verify_password("anything", "not-a-supported-hash")
    assert not needs_rehash(first)


def test_fresh_database_bootstraps_one_owner_without_plaintext_password(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "users.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "temporary-owner-password")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")

    database.init_db()
    database.init_db()

    db = _connect(database_path)
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    assert columns == USER_COLUMNS

    users = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    assert len(users) == 1
    owner = users[0]
    assert owner["username"] == "mark"
    assert owner["display_name"] == "Mark"
    assert owner["role"] == "owner"
    assert owner["active"] == 1
    assert owner["must_change_password"] == 0
    assert owner["password_hash"] != "temporary-owner-password"
    assert "temporary-owner-password" not in owner["password_hash"]
    assert verify_password(
        "temporary-owner-password",
        owner["password_hash"],
    )

    indexes = {
        row["name"]: row
        for row in db.execute("PRAGMA index_list(users)").fetchall()
    }
    assert "idx_users_active_role_username" in indexes
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_owner_bootstrap_waits_when_environment_password_is_missing(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "no-password.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.delenv("MARK_OS_PASSWORD", raising=False)

    database.init_db()

    db = _connect(database_path)
    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    db.close()


def test_existing_user_is_never_overwritten_by_environment_changes(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "preserve-user.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "first-password")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")

    database.init_db()

    db = _connect(database_path)
    original = db.execute("SELECT * FROM users WHERE id = 1").fetchone()
    db.close()

    monkeypatch.setenv("MARK_OS_USERNAME", "replacement")
    monkeypatch.setenv("MARK_OS_PASSWORD", "replacement-password")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Replacement")
    database.init_db()

    db = _connect(database_path)
    users = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    assert len(users) == 1
    assert users[0]["username"] == original["username"]
    assert users[0]["display_name"] == original["display_name"]
    assert users[0]["password_hash"] == original["password_hash"]
    assert verify_password("first-password", users[0]["password_hash"])
    assert not verify_password(
        "replacement-password",
        users[0]["password_hash"],
    )
    db.close()


def test_user_bootstrap_does_not_change_existing_crm_or_quest_rows(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "preserve-crm.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.delenv("MARK_OS_PASSWORD", raising=False)
    database.init_db()

    with database.get_db() as db:
        quest_id = db.execute(
            """
            INSERT INTO tasks (
                title,
                description,
                status,
                quest_source,
                why
            )
            VALUES (
                'Preserve CRM lead',
                'M1 regression fixture',
                'backlog',
                'client_hunting',
                'The user migration must not affect CRM data.'
            )
            """
        ).lastrowid
        db.execute(
            """
            INSERT INTO leads (
                quest_id,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                quest_id,
                "m1-preserve-request",
                "m1-preserve-fingerprint",
                "m1-preserve-dedupe",
                "Protected Analytics",
                "Alex Buyer",
                "Referral",
                "Needs a reporting system",
                "Mark has data engineering experience",
                "Review the opportunity",
            ),
        )
        before_quest = tuple(
            db.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (quest_id,),
            ).fetchone()
        )
        before_lead = tuple(
            db.execute(
                "SELECT * FROM leads WHERE quest_id = ?",
                (quest_id,),
            ).fetchone()
        )

    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")
    database.init_db()

    with database.get_db() as db:
        after_quest = tuple(
            db.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (quest_id,),
            ).fetchone()
        )
        after_lead = tuple(
            db.execute(
                "SELECT * FROM leads WHERE quest_id = ?",
                (quest_id,),
            ).fetchone()
        )
        owner_count = db.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'owner'"
        ).fetchone()[0]

    assert after_quest == before_quest
    assert after_lead == before_lead
    assert owner_count == 1
