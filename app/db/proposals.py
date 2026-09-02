from __future__ import annotations

import sqlite3


PROPOSAL_STATUSES = (
    "draft",
    "internal_review",
    "approved",
    "sent",
)

DECISION_STATUSES = (
    "accepted",
    "rejected",
    "expired",
)

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    lead_id INTEGER NOT NULL,
    service_offered TEXT NOT NULL DEFAULT '',
    engagement_type TEXT NOT NULL DEFAULT '',
    proposed_price_amount_minor_units INTEGER
        CHECK (
            proposed_price_amount_minor_units IS NULL
            OR proposed_price_amount_minor_units >= 0
        ),
    expected_monthly_value_amount_minor_units INTEGER
        CHECK (
            expected_monthly_value_amount_minor_units IS NULL
            OR expected_monthly_value_amount_minor_units >= 0
        ),
    currency TEXT NOT NULL DEFAULT 'PHP',
    proposal_url TEXT NOT NULL DEFAULT '',
    proposal_sent_at TEXT,
    proposal_expires_at TEXT,
    probability INTEGER
        CHECK (probability IS NULL OR (probability BETWEEN 0 AND 100)),
    follow_up_date TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ({", ".join(f"'{value}'" for value in PROPOSAL_STATUSES)})),
    decision_status TEXT
        CHECK (
            decision_status IS NULL
            OR decision_status IN ({", ".join(f"'{value}'" for value in DECISION_STATUSES)})
        ),
    decision_reason TEXT NOT NULL DEFAULT '',
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by_user_id INTEGER,
    updated_by_user_id INTEGER,
    approved_by_user_id INTEGER,
    approved_at TEXT,
    sent_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (approved_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (sent_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_proposals_lead
ON proposals (lead_id, deleted_at, id DESC);

CREATE INDEX IF NOT EXISTS idx_proposals_workspace_status
ON proposals (organization_id, status, deleted_at);
"""

REQUIRED_COLUMNS = {
    "id",
    "organization_id",
    "lead_id",
    "service_offered",
    "engagement_type",
    "proposed_price_amount_minor_units",
    "expected_monthly_value_amount_minor_units",
    "currency",
    "proposal_url",
    "proposal_sent_at",
    "proposal_expires_at",
    "probability",
    "follow_up_date",
    "status",
    "decision_status",
    "decision_reason",
    "row_version",
    "created_by_user_id",
    "updated_by_user_id",
    "approved_by_user_id",
    "approved_at",
    "sent_by_user_id",
    "created_at",
    "updated_at",
    "deleted_at",
}


def _columns(db: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute("PRAGMA table_info(proposals)").fetchall()
    }


def validate_schema(db: sqlite3.Connection) -> None:
    missing = REQUIRED_COLUMNS - _columns(db)
    if missing:
        raise RuntimeError(
            "Proposal schema is incomplete: " + ", ".join(sorted(missing))
        )
