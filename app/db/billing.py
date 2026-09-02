from __future__ import annotations

import sqlite3


BILLING_MODELS = ("retainer", "project", "hourly")
BILLING_PERIODS = ("monthly", "quarterly", "annual", "one_time")
BILLING_ARRANGEMENT_STATUSES = ("active", "cancelled")
INVOICE_STATUSES = ("draft", "sent", "paid", "overdue", "void")
ENGAGEMENT_COST_TYPES = ("pass_through_expense", "contractor_cost", "staff_cost")

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS billing_arrangements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    engagement_id INTEGER NOT NULL,
    billing_model TEXT NOT NULL
        CHECK (billing_model IN ({", ".join(f"'{v}'" for v in BILLING_MODELS)})),
    billing_period TEXT NOT NULL DEFAULT 'monthly'
        CHECK (billing_period IN ({", ".join(f"'{v}'" for v in BILLING_PERIODS)})),
    amount_minor_units INTEGER NOT NULL CHECK (amount_minor_units >= 0),
    currency TEXT NOT NULL DEFAULT 'PHP',
    commission_recipient_user_id INTEGER,
    commission_rate_basis_points INTEGER
        CHECK (
            commission_rate_basis_points IS NULL
            OR (commission_rate_basis_points BETWEEN 0 AND 10000)
        ),
    start_date TEXT NOT NULL,
    renewal_date TEXT,
    cancellation_date TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ({", ".join(f"'{v}'" for v in BILLING_ARRANGEMENT_STATUSES)})),
    notes TEXT NOT NULL DEFAULT '',
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by_user_id INTEGER,
    updated_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (engagement_id) REFERENCES client_engagements(id) ON DELETE CASCADE,
    FOREIGN KEY (commission_recipient_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    engagement_id INTEGER NOT NULL,
    billing_arrangement_id INTEGER,
    invoice_reference TEXT NOT NULL CHECK (TRIM(invoice_reference) <> ''),
    invoice_date TEXT NOT NULL,
    due_date TEXT,
    period_start TEXT,
    period_end TEXT,
    amount_minor_units INTEGER NOT NULL CHECK (amount_minor_units >= 0),
    currency TEXT NOT NULL DEFAULT 'PHP',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ({", ".join(f"'{v}'" for v in INVOICE_STATUSES)})),
    notes TEXT NOT NULL DEFAULT '',
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by_user_id INTEGER,
    updated_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (engagement_id) REFERENCES client_engagements(id) ON DELETE CASCADE,
    FOREIGN KEY (billing_arrangement_id) REFERENCES billing_arrangements(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE (organization_id, invoice_reference)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    invoice_id INTEGER NOT NULL,
    amount_minor_units INTEGER NOT NULL CHECK (amount_minor_units > 0),
    currency TEXT NOT NULL DEFAULT 'PHP',
    payment_date TEXT NOT NULL,
    payment_method TEXT NOT NULL DEFAULT '',
    reference TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    voided_at TEXT,
    voided_by_user_id INTEGER,
    void_reason TEXT NOT NULL DEFAULT '',
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE RESTRICT,
    FOREIGN KEY (voided_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS engagement_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    engagement_id INTEGER NOT NULL,
    cost_type TEXT NOT NULL
        CHECK (cost_type IN ({", ".join(f"'{v}'" for v in ENGAGEMENT_COST_TYPES)})),
    description TEXT NOT NULL CHECK (TRIM(description) <> ''),
    amount_minor_units INTEGER NOT NULL CHECK (amount_minor_units >= 0),
    currency TEXT NOT NULL DEFAULT 'PHP',
    incurred_date TEXT NOT NULL,
    paid_to TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (engagement_id) REFERENCES client_engagements(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_billing_arrangements_engagement
ON billing_arrangements (engagement_id, status);

CREATE INDEX IF NOT EXISTS idx_invoices_engagement
ON invoices (engagement_id, deleted_at, id DESC);

CREATE INDEX IF NOT EXISTS idx_invoices_workspace_status
ON invoices (organization_id, status, deleted_at);

CREATE INDEX IF NOT EXISTS idx_payments_invoice
ON payments (invoice_id, voided_at);

CREATE INDEX IF NOT EXISTS idx_engagement_costs_engagement
ON engagement_costs (engagement_id, deleted_at);
"""

REQUIRED_ARRANGEMENT_COLUMNS = {
    "id",
    "organization_id",
    "engagement_id",
    "billing_model",
    "billing_period",
    "amount_minor_units",
    "currency",
    "commission_recipient_user_id",
    "commission_rate_basis_points",
    "start_date",
    "renewal_date",
    "cancellation_date",
    "status",
    "notes",
    "row_version",
    "created_by_user_id",
    "updated_by_user_id",
    "created_at",
    "updated_at",
}

REQUIRED_INVOICE_COLUMNS = {
    "id",
    "organization_id",
    "engagement_id",
    "billing_arrangement_id",
    "invoice_reference",
    "invoice_date",
    "due_date",
    "period_start",
    "period_end",
    "amount_minor_units",
    "currency",
    "status",
    "notes",
    "row_version",
    "created_by_user_id",
    "updated_by_user_id",
    "created_at",
    "updated_at",
    "deleted_at",
}

REQUIRED_PAYMENT_COLUMNS = {
    "id",
    "organization_id",
    "invoice_id",
    "amount_minor_units",
    "currency",
    "payment_date",
    "payment_method",
    "reference",
    "notes",
    "voided_at",
    "voided_by_user_id",
    "void_reason",
    "created_by_user_id",
    "created_at",
}

REQUIRED_COST_COLUMNS = {
    "id",
    "organization_id",
    "engagement_id",
    "cost_type",
    "description",
    "amount_minor_units",
    "currency",
    "incurred_date",
    "paid_to",
    "notes",
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
    checks = (
        ("billing_arrangements", REQUIRED_ARRANGEMENT_COLUMNS),
        ("invoices", REQUIRED_INVOICE_COLUMNS),
        ("payments", REQUIRED_PAYMENT_COLUMNS),
        ("engagement_costs", REQUIRED_COST_COLUMNS),
    )
    for table_name, required in checks:
        missing = required - _columns(db, table_name)
        if missing:
            raise RuntimeError(
                f"Billing schema is incomplete for {table_name}: "
                + ", ".join(sorted(missing))
            )
