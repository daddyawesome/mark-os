from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from app.services.passwords import hash_password


ROLES = ("owner", "member", "lead_sourcer")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE
        CHECK(length(trim(username)) > 0),
    display_name TEXT NOT NULL
        CHECK(length(trim(display_name)) > 0),
    password_hash TEXT NOT NULL
        CHECK(length(trim(password_hash)) > 0),
    role TEXT NOT NULL DEFAULT 'lead_sourcer'
        CHECK(role IN ('owner', 'member', 'lead_sourcer')),
    active INTEGER NOT NULL DEFAULT 1
        CHECK(active IN (0, 1)),
    must_change_password INTEGER NOT NULL DEFAULT 0
        CHECK(must_change_password IN (0, 1)),
    session_version INTEGER NOT NULL DEFAULT 1
        CHECK(session_version >= 1),
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_users_active_role_username
ON users(active, role, username);
"""


@dataclass(frozen=True)
class OwnerBootstrapResult:
    user_id: int | None
    created: bool
    reason: str


def _clean_required(value: str, field_name: str) -> str:
    clean = (value or "").strip()
    if not clean:
        raise ValueError(f"{field_name} is required.")
    return clean



def migrate(db: sqlite3.Connection) -> None:
    """Add session revocation support to already-live user tables."""
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    if "session_version" not in columns:
        db.execute(
            """
            ALTER TABLE users
            ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1
                CHECK(session_version >= 1)
            """
        )


def migrate_family_roles(db: sqlite3.Connection) -> None:
    # Safely expand the role CHECK without redirecting child foreign keys.
    table_row = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'users'
        """
    ).fetchone()
    if table_row is None or table_row["sql"] is None:
        return

    normalized_sql = " ".join(table_row["sql"].lower().split())
    if "check(role in ('owner', 'member', 'lead_sourcer'))" in normalized_sql:
        return

    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    if "session_version" not in columns:
        raise RuntimeError(
            "M7 requires the M5/M6 session_version migration first."
        )

    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")

    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DROP TABLE IF EXISTS users_m7_new")
        db.execute(
            """
            CREATE TABLE users_m7_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE
                    CHECK(length(trim(username)) > 0),
                display_name TEXT NOT NULL
                    CHECK(length(trim(display_name)) > 0),
                password_hash TEXT NOT NULL
                    CHECK(length(trim(password_hash)) > 0),
                role TEXT NOT NULL DEFAULT 'lead_sourcer'
                    CHECK(role IN ('owner', 'member', 'lead_sourcer')),
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
            INSERT INTO users_m7_new (
                id,
                username,
                display_name,
                password_hash,
                role,
                active,
                must_change_password,
                session_version,
                last_login_at,
                created_at,
                updated_at
            )
            SELECT
                id,
                username,
                display_name,
                password_hash,
                role,
                active,
                must_change_password,
                session_version,
                last_login_at,
                created_at,
                updated_at
            FROM users
            ORDER BY id
            """
        )
        db.execute("DROP TABLE users")
        db.execute("ALTER TABLE users_m7_new RENAME TO users")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")

    violations = db.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            "M7 users migration produced foreign-key violations."
        )

def validate_schema(db: sqlite3.Connection) -> None:
    """Reject partial or weakened user schemas without rewriting user data."""
    table_info = db.execute("PRAGMA table_info(users)").fetchall()
    columns = {row["name"]: row for row in table_info}

    required_columns = {
        "id",
        "username",
        "display_name",
        "password_hash",
        "role",
        "active",
        "must_change_password",
        "session_version",
        "last_login_at",
        "created_at",
        "updated_at",
    }
    missing = required_columns - set(columns)
    if missing:
        raise RuntimeError(
            "Incompatible users schema; missing columns: "
            + ", ".join(sorted(missing))
        )

    required_not_null = {
        "username",
        "display_name",
        "password_hash",
        "role",
        "active",
        "must_change_password",
        "session_version",
        "created_at",
        "updated_at",
    }
    nullable = {
        name for name in required_not_null if not columns[name]["notnull"]
    }
    if nullable:
        raise RuntimeError(
            "Incompatible users schema; required columns are nullable: "
            + ", ".join(sorted(nullable))
        )

    if columns["id"]["type"].upper() != "INTEGER" or columns["id"]["pk"] != 1:
        raise RuntimeError(
            "Incompatible users schema; id must be INTEGER PRIMARY KEY"
        )

    if columns["session_version"]["type"].upper() != "INTEGER":
        raise RuntimeError(
            "Incompatible users schema; session_version must be INTEGER"
        )

    expected_defaults = {
        "role": "'lead_sourcer'",
        "active": "1",
        "must_change_password": "0",
        "session_version": "1",
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "CURRENT_TIMESTAMP",
    }
    wrong_defaults = {
        name
        for name, expected in expected_defaults.items()
        if columns[name]["dflt_value"] != expected
    }
    if wrong_defaults:
        raise RuntimeError(
            "Incompatible users schema; columns have incorrect defaults: "
            + ", ".join(sorted(wrong_defaults))
        )

    table_row = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'users'
        """
    ).fetchone()
    if table_row is None or table_row["sql"] is None:
        raise RuntimeError("Incompatible users schema; table definition is missing")

    normalized_sql = " ".join(table_row["sql"].lower().split())
    required_fragments = (
        "username text not null collate nocase unique",
        "check(length(trim(username)) > 0)",
        "check(length(trim(display_name)) > 0)",
        "check(length(trim(password_hash)) > 0)",
        "check(role in ('owner', 'member', 'lead_sourcer'))",
        "check(active in (0, 1))",
        "check(must_change_password in (0, 1))",
        "check(session_version >= 1)",
    )
    if any(fragment not in normalized_sql for fragment in required_fragments):
        raise RuntimeError(
            "Incompatible users schema; required constraints are missing"
        )


def validate_indexes(db: sqlite3.Connection) -> None:
    rows = {
        row["name"]: row
        for row in db.execute("PRAGMA index_list(users)").fetchall()
    }
    index = rows.get("idx_users_active_role_username")
    columns = [
        row["name"]
        for row in db.execute(
            "PRAGMA index_info(idx_users_active_role_username)"
        ).fetchall()
    ]
    if (
        index is None
        or bool(index["unique"])
        or bool(index["partial"])
        or columns != ["active", "role", "username"]
    ):
        raise RuntimeError(
            "Incompatible users index: idx_users_active_role_username"
        )


def bootstrap_owner_from_environment(
    db: sqlite3.Connection,
) -> OwnerBootstrapResult:
    """Create the first owner from the current environment login once.

    M1 does not change the login flow. Existing users are never overwritten,
    and the password hash is not regenerated on ordinary startup.
    """
    existing = db.execute(
        "SELECT id FROM users ORDER BY id LIMIT 1"
    ).fetchone()
    if existing is not None:
        return OwnerBootstrapResult(
            user_id=existing["id"],
            created=False,
            reason="users_already_exist",
        )

    username = (os.getenv("MARK_OS_USERNAME", "mark") or "").strip()
    password = os.getenv("MARK_OS_PASSWORD", "")
    display_name = (
        os.getenv("MARK_OS_DISPLAY_NAME", "")
        or username
        or "Mark"
    ).strip()

    if not password:
        return OwnerBootstrapResult(
            user_id=None,
            created=False,
            reason="password_not_configured",
        )

    username = _clean_required(username, "Username")
    display_name = _clean_required(display_name, "Display name")
    password_hash = hash_password(password)

    cursor = db.execute(
        """
        INSERT INTO users (
            username,
            display_name,
            password_hash,
            role,
            active,
            must_change_password
        )
        VALUES (?, ?, ?, 'owner', 1, 0)
        """,
        (username, display_name, password_hash),
    )
    return OwnerBootstrapResult(
        user_id=cursor.lastrowid,
        created=True,
        reason="owner_created",
    )
