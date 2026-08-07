from __future__ import annotations

import sqlite3


ITEM_TYPES = (
    "service",
    "project",
    "case_study",
    "relationship",
    "content_draft",
    "meeting_preparation",
    "document",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS organization_company_profiles (
    organization_id INTEGER PRIMARY KEY,
    founder_plan TEXT NOT NULL DEFAULT '',
    about_company TEXT NOT NULL DEFAULT '',
    company_cv TEXT NOT NULL DEFAULT '',
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by_user_id INTEGER,
    updated_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS organization_knowledge_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    item_type TEXT NOT NULL CHECK (
        item_type IN (
            'service',
            'project',
            'case_study',
            'relationship',
            'content_draft',
            'meeting_preparation',
            'document'
        )
    ),
    title TEXT NOT NULL CHECK (TRIM(title) <> ''),
    subtitle TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '',
    reference_url TEXT NOT NULL DEFAULT '',
    scheduled_for TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active')),
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by_user_id INTEGER,
    updated_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_organization_knowledge_workspace_type
ON organization_knowledge_items (
    organization_id,
    item_type,
    deleted_at,
    status,
    id
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_knowledge_active_title
ON organization_knowledge_items (
    organization_id,
    item_type,
    title COLLATE NOCASE
)
WHERE deleted_at IS NULL;
"""

FOUNDER_PLAN = """Leadership
Rey — Managing Director / Chief Statistical Officer
Mark — Co-Founder / Chief Technology & Data Officer
Freddy — Senior Statistical Consultant / Lead Researcher

What we build around
- Research & statistics
- Data analysis & BI
- Data engineering & automation
- Practical AI where it creates real value

Who we can serve
- Researchers & universities
- Healthcare
- NGOs
- SMEs

Operating rule
Record leads, projects, tasks, decisions, revenue, and expenses in MARK-OS so Pendang keeps one operational history.

First objective
Leads → Clients → Projects → Payment → Referrals"""

SEED_SERVICES = (
    (
        "Research & Statistics",
        "Statistical analysis, research support, and evidence-focused work.",
    ),
    (
        "Data Analysis & BI",
        "Decision-ready reporting, dashboards, and analytical workflows.",
    ),
    (
        "Data Engineering & Automation",
        "Reliable data movement, recurring reporting, and workflow automation.",
    ),
    (
        "Practical AI",
        "Applied AI only where it creates measurable operational value.",
    ),
)

REQUIRED_PROFILE_COLUMNS = {
    "organization_id",
    "founder_plan",
    "about_company",
    "company_cv",
    "row_version",
    "created_by_user_id",
    "updated_by_user_id",
    "created_at",
    "updated_at",
}

REQUIRED_ITEM_COLUMNS = {
    "id",
    "organization_id",
    "item_type",
    "title",
    "subtitle",
    "body",
    "details",
    "reference_url",
    "scheduled_for",
    "status",
    "row_version",
    "created_by_user_id",
    "updated_by_user_id",
    "created_at",
    "updated_at",
    "deleted_at",
}


def _columns(db: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def seed(db: sqlite3.Connection) -> None:
    organization = db.execute(
        "SELECT id FROM organizations WHERE slug = 'pendang'"
    ).fetchone()
    if organization is None:
        return

    organization_id = int(organization["id"])
    db.execute(
        """
        INSERT OR IGNORE INTO organization_company_profiles (
            organization_id,
            founder_plan
        )
        VALUES (?, ?)
        """,
        (organization_id, FOUNDER_PLAN),
    )

    for title, body in SEED_SERVICES:
        db.execute(
            """
            INSERT INTO organization_knowledge_items (
                organization_id,
                item_type,
                title,
                body,
                status
            )
            SELECT ?, 'service', ?, ?, 'active'
            WHERE NOT EXISTS (
                SELECT 1
                FROM organization_knowledge_items
                WHERE organization_id = ?
                  AND item_type = 'service'
                  AND title = ? COLLATE NOCASE
                  AND deleted_at IS NULL
            )
            """,
            (organization_id, title, body, organization_id, title),
        )


def validate_schema(db: sqlite3.Connection) -> None:
    profile_columns = _columns(db, "organization_company_profiles")
    missing_profile = REQUIRED_PROFILE_COLUMNS - profile_columns
    if missing_profile:
        raise RuntimeError(
            "Pendang company profile schema is incomplete: "
            + ", ".join(sorted(missing_profile))
        )

    item_columns = _columns(db, "organization_knowledge_items")
    missing_items = REQUIRED_ITEM_COLUMNS - item_columns
    if missing_items:
        raise RuntimeError(
            "Pendang company knowledge schema is incomplete: "
            + ", ".join(sorted(missing_items))
        )

    organization = db.execute(
        "SELECT id FROM organizations WHERE slug = 'pendang'"
    ).fetchone()
    if organization is None:
        return

    profile = db.execute(
        """
        SELECT organization_id, founder_plan, row_version
        FROM organization_company_profiles
        WHERE organization_id = ?
        """,
        (int(organization["id"]),),
    ).fetchone()
    if profile is None or not str(profile["founder_plan"] or "").strip():
        raise RuntimeError("Pendang Founder Plan seed is missing.")
    if int(profile["row_version"]) < 1:
        raise RuntimeError("Pendang company profile row version is invalid.")
