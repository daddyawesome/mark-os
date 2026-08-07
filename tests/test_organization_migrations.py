from __future__ import annotations

import sqlite3

import pytest

from app import database


def _connect(database_path) -> sqlite3.Connection:
    db = sqlite3.connect(database_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _initialize(database_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "test-password")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")
    database.init_db()


def _organization_ids(db: sqlite3.Connection) -> dict[str, int]:
    return {
        row["slug"]: row["id"]
        for row in db.execute(
            "SELECT id, slug FROM organizations ORDER BY id"
        ).fetchall()
    }


def test_organization_schema_seeds_idempotently_and_preserves_users(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "organizations.db"
    _initialize(database_path, monkeypatch)

    db = _connect(database_path)
    tables = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"organizations", "organization_memberships"} <= tables
    assert db.execute(
        "SELECT name FROM organizations WHERE slug = 'mark-agency'"
    ).fetchone()["name"] == "MARK Agency"
    assert db.execute(
        "SELECT name FROM organizations WHERE slug = 'pendang'"
    ).fetchone()["name"] == "Pendang Research & Analytics"

    original_user = db.execute(
        "SELECT id, username, display_name, role FROM users"
    ).fetchall()
    original_ids = _organization_ids(db)
    db.close()

    database.init_db()

    db = _connect(database_path)
    assert db.execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 2
    assert _organization_ids(db) == original_ids
    assert [tuple(row) for row in db.execute(
        "SELECT id, username, display_name, role FROM users"
    ).fetchall()] == [tuple(row) for row in original_user]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_existing_organization_name_is_not_overwritten_by_reseeding(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "organization-name.db"
    _initialize(database_path, monkeypatch)

    db = _connect(database_path)
    db.execute(
        "UPDATE organizations SET name = 'Custom Agency Name' "
        "WHERE slug = 'mark-agency'"
    )
    db.commit()
    db.close()

    database.init_db()

    db = _connect(database_path)
    assert db.execute(
        "SELECT name FROM organizations WHERE slug = 'mark-agency'"
    ).fetchone()["name"] == "Custom Agency Name"
    db.close()


def test_organization_constraints_and_membership_persist(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "organization-constraints.db"
    _initialize(database_path, monkeypatch)

    db = _connect(database_path)
    user_id = db.execute(
        """
        INSERT INTO users (
            username,
            display_name,
            password_hash,
            role
        )
        VALUES (?, ?, ?, 'lead_sourcer')
        """,
        ("membership-test-user", "Membership Test User", "test-hash"),
    ).lastrowid
    organization_id = db.execute(
        "SELECT id FROM organizations WHERE slug = 'pendang'"
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO organizations (slug, name) VALUES (?, ?)",
            ("PENDANG", "Duplicate Pendang"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO organizations (slug, name) VALUES (?, ?)",
            ("   ", "Invalid"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO organizations (slug, name) VALUES (?, ?)",
            ("invalid-name", "  "),
        )

    db.execute(
        """
        INSERT INTO organization_memberships
            (user_id, organization_id, membership_role)
        VALUES (?, ?, ?)
        """,
        (user_id, organization_id, "workspace_owner"),
    )
    membership = db.execute(
        """
        SELECT membership_role
        FROM organization_memberships
        WHERE user_id = ? AND organization_id = ?
        """,
        (user_id, organization_id),
    ).fetchone()
    assert membership["membership_role"] == "workspace_owner"

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO organization_memberships
                (user_id, organization_id, membership_role)
            VALUES (?, ?, ?)
            """,
            (user_id, organization_id, "workspace_admin"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO organization_memberships
                (user_id, organization_id, membership_role)
            VALUES (?, ?, ?)
            """,
            (user_id, organization_id, "owner"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO organization_memberships
                (user_id, organization_id, membership_role)
            VALUES (?, ?, ?)
            """,
            (999999, organization_id, "crm_contributor"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO organization_memberships
                (user_id, organization_id, membership_role)
            VALUES (?, ?, ?)
            """,
            (user_id, 999999, "crm_contributor"),
        )
    db.close()