from __future__ import annotations

import sqlite3


INTAKE_OUTCOMES = ("created", "duplicate", "rejected")

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS webhook_intake_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    source_name TEXT NOT NULL CHECK (TRIM(source_name) <> ''),
    token_hash TEXT NOT NULL UNIQUE,
    token_last_four TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT,
    revoked_by_user_id INTEGER,
    last_used_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (revoked_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS webhook_intake_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL,
    organization_id INTEGER NOT NULL,
    external_id TEXT NOT NULL CHECK (TRIM(external_id) <> ''),
    outcome TEXT NOT NULL CHECK (outcome IN ({", ".join(f"'{value}'" for value in INTAKE_OUTCOMES)})),
    lead_id INTEGER,
    error_summary TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (token_id) REFERENCES webhook_intake_tokens(id) ON DELETE CASCADE,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE SET NULL
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_webhook_intake_tokens_workspace
ON webhook_intake_tokens (organization_id, active);

CREATE INDEX IF NOT EXISTS idx_webhook_intake_events_workspace
ON webhook_intake_events (organization_id, received_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_intake_events_dedupe
ON webhook_intake_events (token_id, external_id);
"""

REQUIRED_TOKEN_COLUMNS = {
    "id",
    "organization_id",
    "source_name",
    "token_hash",
    "token_last_four",
    "active",
    "created_by_user_id",
    "created_at",
    "revoked_at",
    "revoked_by_user_id",
    "last_used_at",
}

REQUIRED_EVENT_COLUMNS = {
    "id",
    "token_id",
    "organization_id",
    "external_id",
    "outcome",
    "lead_id",
    "error_summary",
    "received_at",
}


def _columns(db: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def validate_schema(db: sqlite3.Connection) -> None:
    missing_tokens = REQUIRED_TOKEN_COLUMNS - _columns(db, "webhook_intake_tokens")
    if missing_tokens:
        raise RuntimeError(
            "Webhook intake token schema is incomplete: "
            + ", ".join(sorted(missing_tokens))
        )
    missing_events = REQUIRED_EVENT_COLUMNS - _columns(db, "webhook_intake_events")
    if missing_events:
        raise RuntimeError(
            "Webhook intake event schema is incomplete: "
            + ", ".join(sorted(missing_events))
        )
