from __future__ import annotations

import sqlite3

from app.db.schema import table_exists


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS playbooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL COLLATE NOCASE UNIQUE
        CHECK(length(trim(slug)) > 0),
    title TEXT NOT NULL
        CHECK(length(trim(title)) > 0),
    markdown_content TEXT NOT NULL
        CHECK(length(trim(markdown_content)) > 0),
    active INTEGER NOT NULL DEFAULT 1
        CHECK(active IN (0, 1)),
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by_user_id)
        REFERENCES users(id)
        ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS user_playbook_assignments (
    user_id INTEGER NOT NULL,
    playbook_id INTEGER NOT NULL,
    assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, playbook_id),
    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,
    FOREIGN KEY (playbook_id)
        REFERENCES playbooks(id)
        ON DELETE CASCADE
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_playbooks_active_slug
ON playbooks(active, slug);

CREATE INDEX IF NOT EXISTS idx_playbook_assignments_user
ON user_playbook_assignments(user_id, assigned_at DESC, playbook_id);
"""


def validate_schema(db: sqlite3.Connection) -> None:
    for table_name in ("playbooks", "user_playbook_assignments"):
        if not table_exists(db, table_name):
            raise RuntimeError(
                f"Incompatible playbook schema; {table_name} is missing"
            )

    playbook_columns = {
        row["name"]: row
        for row in db.execute("PRAGMA table_info(playbooks)").fetchall()
    }
    required_playbook_columns = {
        "id",
        "slug",
        "title",
        "markdown_content",
        "active",
        "created_by_user_id",
        "created_at",
        "updated_at",
    }
    missing = required_playbook_columns - set(playbook_columns)
    if missing:
        raise RuntimeError(
            "Incompatible playbook schema; missing columns: "
            + ", ".join(sorted(missing))
        )

    assignment_columns = {
        row["name"]: row
        for row in db.execute(
            "PRAGMA table_info(user_playbook_assignments)"
        ).fetchall()
    }
    required_assignment_columns = {
        "user_id",
        "playbook_id",
        "assigned_at",
    }
    missing_assignments = (
        required_assignment_columns - set(assignment_columns)
    )
    if missing_assignments:
        raise RuntimeError(
            "Incompatible playbook assignment schema; missing columns: "
            + ", ".join(sorted(missing_assignments))
        )

    if db.execute("PRAGMA foreign_key_check(playbooks)").fetchall():
        raise RuntimeError("Incompatible playbook data; foreign-key errors")
    if db.execute(
        "PRAGMA foreign_key_check(user_playbook_assignments)"
    ).fetchall():
        raise RuntimeError(
            "Incompatible playbook assignments; foreign-key errors"
        )


def validate_indexes(db: sqlite3.Connection) -> None:
    expected = {
        "idx_playbooks_active_slug": (
            "playbooks",
            ["active", "slug"],
        ),
        "idx_playbook_assignments_user": (
            "user_playbook_assignments",
            ["user_id", "assigned_at", "playbook_id"],
        ),
    }

    for index_name, (table_name, expected_columns) in expected.items():
        rows = {
            row["name"]: row
            for row in db.execute(
                f"PRAGMA index_list({table_name})"
            ).fetchall()
        }
        index = rows.get(index_name)
        columns = [
            row["name"]
            for row in db.execute(
                f"PRAGMA index_info({index_name})"
            ).fetchall()
        ]
        if (
            index is None
            or bool(index["unique"])
            or bool(index["partial"])
            or columns != expected_columns
        ):
            raise RuntimeError(
                f"Incompatible playbook index: {index_name}"
            )
