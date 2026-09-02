from __future__ import annotations

import sqlite3


ENGAGEMENT_STATUSES = ("active", "completed", "cancelled")
ENGAGEMENT_ITEM_TYPES = ("milestone", "task")
ENGAGEMENT_ITEM_STATUSES = ("pending", "in_progress", "completed")

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS organization_clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    lead_id INTEGER NOT NULL UNIQUE,
    company TEXT NOT NULL CHECK (TRIM(company) <> ''),
    contact_person TEXT NOT NULL DEFAULT '',
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE RESTRICT,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS client_engagements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    client_id INTEGER NOT NULL,
    title TEXT NOT NULL CHECK (TRIM(title) <> ''),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ({", ".join(f"'{value}'" for value in ENGAGEMENT_STATUSES)})),
    delivery_owner_user_id INTEGER,
    success_criteria TEXT NOT NULL DEFAULT '',
    deliverables TEXT NOT NULL DEFAULT '',
    contract_url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by_user_id INTEGER,
    updated_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (client_id) REFERENCES organization_clients(id) ON DELETE CASCADE,
    FOREIGN KEY (delivery_owner_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS engagement_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    engagement_id INTEGER NOT NULL,
    item_type TEXT NOT NULL
        CHECK (item_type IN ({", ".join(f"'{value}'" for value in ENGAGEMENT_ITEM_TYPES)})),
    title TEXT NOT NULL CHECK (TRIM(title) <> ''),
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ({", ".join(f"'{value}'" for value in ENGAGEMENT_ITEM_STATUSES)})),
    due_date TEXT,
    assigned_to_user_id INTEGER,
    completed_at TEXT,
    completed_by_user_id INTEGER,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (engagement_id) REFERENCES client_engagements(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_to_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (completed_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_organization_clients_workspace
ON organization_clients (organization_id);

CREATE INDEX IF NOT EXISTS idx_client_engagements_client
ON client_engagements (client_id, deleted_at, id DESC);

CREATE INDEX IF NOT EXISTS idx_client_engagements_workspace_status
ON client_engagements (organization_id, status, deleted_at);

CREATE INDEX IF NOT EXISTS idx_engagement_items_engagement
ON engagement_items (engagement_id, deleted_at, item_type, id DESC);
"""

REQUIRED_CLIENT_COLUMNS = {
    "id",
    "organization_id",
    "lead_id",
    "company",
    "contact_person",
    "row_version",
    "created_by_user_id",
    "created_at",
    "updated_at",
}

REQUIRED_ENGAGEMENT_COLUMNS = {
    "id",
    "organization_id",
    "client_id",
    "title",
    "status",
    "delivery_owner_user_id",
    "success_criteria",
    "deliverables",
    "contract_url",
    "notes",
    "started_at",
    "completed_at",
    "row_version",
    "created_by_user_id",
    "updated_by_user_id",
    "created_at",
    "updated_at",
    "deleted_at",
}

REQUIRED_ITEM_COLUMNS = {
    "id",
    "organization_id",
    "engagement_id",
    "item_type",
    "title",
    "description",
    "status",
    "due_date",
    "assigned_to_user_id",
    "completed_at",
    "completed_by_user_id",
    "row_version",
    "created_by_user_id",
    "created_at",
    "updated_at",
    "deleted_at",
}


def _columns(db: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def validate_schema(db: sqlite3.Connection) -> None:
    missing_clients = REQUIRED_CLIENT_COLUMNS - _columns(db, "organization_clients")
    if missing_clients:
        raise RuntimeError(
            "Client schema is incomplete: " + ", ".join(sorted(missing_clients))
        )
    missing_engagements = REQUIRED_ENGAGEMENT_COLUMNS - _columns(
        db, "client_engagements"
    )
    if missing_engagements:
        raise RuntimeError(
            "Client engagement schema is incomplete: "
            + ", ".join(sorted(missing_engagements))
        )
    missing_items = REQUIRED_ITEM_COLUMNS - _columns(db, "engagement_items")
    if missing_items:
        raise RuntimeError(
            "Engagement item schema is incomplete: "
            + ", ".join(sorted(missing_items))
        )
