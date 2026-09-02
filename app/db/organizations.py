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
    active INTEGER NOT NULL DEFAULT 1
        CHECK(active IN (0, 1)),
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

CREATE INDEX IF NOT EXISTS idx_organization_memberships_active_user
ON organization_memberships(user_id, active, organization_id);
"""


def migrate(db: sqlite3.Connection) -> None:
    """Add independently revocable workspace membership state."""
    if not table_exists(db, "organization_memberships"):
        return
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(organization_memberships)")
    }
    if "active" not in columns:
        db.execute(
            """
            ALTER TABLE organization_memberships
            ADD COLUMN active INTEGER NOT NULL DEFAULT 1
                CHECK(active IN (0, 1))
            """
        )
    if "can_contact_leads" not in columns:
        db.execute(
            """
            ALTER TABLE organization_memberships
            ADD COLUMN can_contact_leads INTEGER NOT NULL DEFAULT 0
                CHECK(can_contact_leads IN (0, 1))
            """
        )


def validate_schema(db: sqlite3.Connection) -> None:
    for table_name in ("organizations", "organization_memberships"):
        if not table_exists(db, table_name):
            raise RuntimeError(
                f"Incompatible organization schema; {table_name} is missing"
            )
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(organization_memberships)")
    }
    if "active" not in columns:
        raise RuntimeError(
            "Incompatible organization schema; membership active state is missing"
        )
    if "can_contact_leads" not in columns:
        raise RuntimeError(
            "Incompatible organization schema; delegated outreach permission "
            "column is missing"
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
            membership_role,
            active
        )
        SELECT
            u.id,
            o.id,
            'workspace_admin',
            1
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
        SET membership_role = 'workspace_admin',
            active = 1
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
          AND (membership_role <> 'workspace_admin' OR active <> 1)
        """
    )

def organization_id_by_slug(
    db: sqlite3.Connection,
    slug: str,
) -> int:
    clean_slug = str(slug or "").strip()
    if not clean_slug:
        raise ValueError("Organization slug is required.")
    row = db.execute(
        "SELECT id FROM organizations WHERE slug = ? COLLATE NOCASE",
        (clean_slug,),
    ).fetchone()
    if row is None:
        raise ValueError("Organization not found.")
    return int(row["id"])


def ensure_legacy_crm_workspace_memberships(
    db: sqlite3.Connection,
) -> None:
    """Place only still-unscoped legacy CRM staff in MARK Agency.

    Future Pendang accounts are created with an explicit membership and are
    therefore excluded by the NOT EXISTS guard.
    """
    db.execute(
        """
        INSERT OR IGNORE INTO organization_memberships (
            user_id,
            organization_id,
            membership_role,
            active
        )
        SELECT
            u.id,
            o.id,
            'crm_contributor',
            1
        FROM users AS u
        JOIN organizations AS o
          ON o.slug = 'mark-agency' COLLATE NOCASE
        WHERE u.active = 1
          AND u.role IN ('lead_sourcer', 'relationship_manager')
          AND NOT EXISTS (
              SELECT 1
              FROM organization_memberships AS existing
              WHERE existing.user_id = u.id
          )
        """
    )
