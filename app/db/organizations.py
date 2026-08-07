from __future__ import annotations

import sqlite3

from app.db.schema import table_exists


MEMBERSHIP_ROLES = (
    "workspace_admin",
    "workspace_owner",
    "crm_contributor",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL COLLATE NOCASE UNIQUE
        CHECK(length(trim(slug)) > 0),
    name TEXT NOT NULL
        CHECK(length(trim(name)) > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organization_memberships (
    user_id INTEGER NOT NULL,
    organization_id INTEGER NOT NULL,
    membership_role TEXT NOT NULL
        CHECK(membership_role IN (
            'workspace_admin',
            'workspace_owner',
            'crm_contributor'
        )),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, organization_id),
    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT,
    FOREIGN KEY (organization_id)
        REFERENCES organizations(id)
        ON DELETE RESTRICT
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_organization_memberships_organization
ON organization_memberships(organization_id, user_id);
"""


def validate_schema(db: sqlite3.Connection) -> None:
    for table_name in ("organizations", "organization_memberships"):
        if not table_exists(db, table_name):
            raise RuntimeError(
                f"Incompatible organization schema; {table_name} is missing"
            )


def seed(db: sqlite3.Connection) -> None:
    db.executemany(
        """
        INSERT OR IGNORE INTO organizations (slug, name)
        VALUES (?, ?)
        """,
        (
            ("mark-agency", "MARK Agency"),
            ("pendang", "Pendang Research & Analytics"),
        ),
    )


def ensure_owner_workspace_memberships(db: sqlite3.Connection) -> None:
    """Give every active global owner admin membership in both core workspaces."""
    db.execute(
        """
        INSERT OR IGNORE INTO organization_memberships (
            user_id,
            organization_id,
            membership_role
        )
        SELECT
            u.id,
            o.id,
            'workspace_admin'
        FROM users AS u
        CROSS JOIN organizations AS o
        WHERE u.role = 'owner'
          AND u.active = 1
          AND o.slug IN ('mark-agency', 'pendang')
        """
    )
    db.execute(
        """
        UPDATE organization_memberships
        SET membership_role = 'workspace_admin'
        WHERE user_id IN (
            SELECT id
            FROM users
            WHERE role = 'owner' AND active = 1
        )
          AND organization_id IN (
            SELECT id
            FROM organizations
            WHERE slug IN ('mark-agency', 'pendang')
        )
          AND membership_role <> 'workspace_admin'
        """
    )
