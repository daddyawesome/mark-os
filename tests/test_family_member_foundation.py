from __future__ import annotations

import sqlite3

from app import database
from app.services.access_control import (
    can_access_request,
    landing_path_for_user,
    permitted_destination,
)
from app.services.team_users import (
    create_lead_sourcer,
    create_member,
)
from app.services.users import authenticate_user


OWNER = {
    "id": 1,
    "username": "mark",
    "display_name": "Mark",
    "role": "owner",
}

MEMBER = {
    "id": 2,
    "username": "wife",
    "display_name": "Wife",
    "role": "member",
}

LEAD_SOURCER = {
    "id": 3,
    "username": "brother",
    "display_name": "Brother",
    "role": "lead_sourcer",
}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def test_member_role_is_created_and_authenticates(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "member-role.db"
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
        authenticated = authenticate_user(
            db,
            "wife",
            "family-pass-123",
        )

    assert member["role"] == "member"
    assert authenticated is not None
    assert authenticated["role"] == "member"


def test_existing_owner_and_sourcer_survive_role_constraint_rebuild(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "family-role-migration.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        sourcer = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="sourcer-pass-123",
            password_confirmation="sourcer-pass-123",
        )
        before = [
            dict(row)
            for row in db.execute(
                """
                SELECT
                    id,
                    username,
                    display_name,
                    password_hash,
                    role,
                    active,
                    session_version
                FROM users
                ORDER BY id
                """
            ).fetchall()
        ]

        # Simulate the M5/M6 role constraint without renaming the live
        # users table. Renaming would redirect child foreign keys.
        db.commit()
        db.execute("PRAGMA foreign_keys = OFF")
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                CREATE TABLE users_m7_fixture (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE
                        CHECK(length(trim(username)) > 0),
                    display_name TEXT NOT NULL
                        CHECK(length(trim(display_name)) > 0),
                    password_hash TEXT NOT NULL
                        CHECK(length(trim(password_hash)) > 0),
                    role TEXT NOT NULL DEFAULT 'lead_sourcer'
                        CHECK(role IN ('owner', 'lead_sourcer')),
                    active INTEGER NOT NULL DEFAULT 1
                        CHECK(active IN (0, 1)),
                    must_change_password INTEGER NOT NULL DEFAULT 0
                        CHECK(must_change_password IN (0, 1)),
                    session_version INTEGER NOT NULL DEFAULT 1
                        CHECK(session_version >= 1),
                    last_login_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            db.execute(
                """
                INSERT INTO users_m7_fixture
                SELECT * FROM users
                """
            )
            db.execute("DROP TABLE users")
            db.execute(
                "ALTER TABLE users_m7_fixture RENAME TO users"
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.execute("PRAGMA foreign_keys = ON")

    database.init_db()

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    after = [
        dict(row)
        for row in connection.execute(
            """
            SELECT
                id,
                username,
                display_name,
                password_hash,
                role,
                active,
                session_version
            FROM users
            ORDER BY id
            """
        ).fetchall()
    ]
    table_sql = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'users'
        """
    ).fetchone()["sql"]
    connection.close()

    assert after == before
    assert sourcer["role"] == "lead_sourcer"
    assert "'member'" in table_sql


def test_member_is_confined_to_private_personal_os():
    allowed = (
        ("GET", "/"),
        ("GET", "/goals"),
        ("GET", "/quests"),
        ("GET", "/quests/1"),
        ("GET", "/history"),
        ("GET", "/life-os"),
        ("POST", "/check-in"),
        ("POST", "/quests"),
        ("POST", "/logout"),
    )
    denied = (
        ("GET", "/crm"),
        ("GET", "/settings/users"),
        ("POST", "/crm/leads"),
    )

    assert all(
        can_access_request(MEMBER, method, path)
        for method, path in allowed
    )
    assert not any(
        can_access_request(MEMBER, method, path)
        for method, path in denied
    )
    assert landing_path_for_user(MEMBER) == "/"
    assert permitted_destination(MEMBER, "/") == "/"
    assert permitted_destination(MEMBER, "/crm") == "/"


def test_owner_and_lead_sourcer_permissions_remain_unchanged():
    assert can_access_request(OWNER, "GET", "/")
    assert can_access_request(OWNER, "GET", "/settings/users")
    assert landing_path_for_user(OWNER) == "/"

    assert can_access_request(LEAD_SOURCER, "GET", "/crm")
    assert can_access_request(
        LEAD_SOURCER,
        "POST",
        "/crm/leads",
    )
    assert not can_access_request(
        LEAD_SOURCER,
        "GET",
        "/settings/users",
    )
    assert landing_path_for_user(LEAD_SOURCER) == "/crm"
