from __future__ import annotations

import sqlite3


TEMPLATE_CATEGORIES = (
    "warm_introduction",
    "linkedin_message",
    "email_introduction",
    "follow_up",
    "meeting_handoff",
    "objection_response",
)

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS outreach_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    slug TEXT NOT NULL,
    title TEXT NOT NULL CHECK (TRIM(title) <> ''),
    category TEXT NOT NULL CHECK (
        category IN (
            {", ".join(f"'{value}'" for value in TEMPLATE_CATEGORIES)}
        )
    ),
    body TEXT NOT NULL CHECK (TRIM(body) <> ''),
    approved INTEGER NOT NULL DEFAULT 0 CHECK (approved IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by_user_id INTEGER,
    updated_by_user_id INTEGER,
    approved_by_user_id INTEGER,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (approved_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);
"""

INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_templates_workspace_slug
ON outreach_templates (organization_id, slug);

CREATE INDEX IF NOT EXISTS idx_outreach_templates_workspace_approved
ON outreach_templates (organization_id, approved, active);
"""

REQUIRED_COLUMNS = {
    "id",
    "organization_id",
    "slug",
    "title",
    "category",
    "body",
    "approved",
    "active",
    "row_version",
    "created_by_user_id",
    "updated_by_user_id",
    "approved_by_user_id",
    "approved_at",
    "created_at",
    "updated_at",
}

# Deliberately generic starter wording using {{variable}} placeholders. Mark
# must review and approve each one per workspace before any Relationship
# Manager can see or copy it; nothing here names a real client or price.
SEED_TEMPLATES = (
    (
        "warm-introduction",
        "Warm introduction",
        "warm_introduction",
        (
            "Hi {{contact_person}}, I'm {{sender_name}} from "
            "{{workspace_name}}. {{opening_note}} Would you be open to a "
            "short conversation about {{topic}}?"
        ),
    ),
    (
        "linkedin-message",
        "LinkedIn message",
        "linkedin_message",
        (
            "Hi {{contact_person}}, I came across {{company}} and "
            "{{opening_note}}. I'm {{sender_name}} from {{workspace_name}} "
            "— open to connecting?"
        ),
    ),
    (
        "email-introduction",
        "Email introduction",
        "email_introduction",
        (
            "Subject: {{subject}}\n\n"
            "Hi {{contact_person}},\n\n"
            "{{opening_note}}\n\n"
            "{{call_to_action}}\n\n"
            "Best,\n{{sender_name}}\n{{workspace_name}}"
        ),
    ),
    (
        "follow-up",
        "3-5 business-day follow-up",
        "follow_up",
        (
            "Hi {{contact_person}}, following up on my note about "
            "{{topic}}. {{follow_up_note}} Let me know if now's a good "
            "time to continue the conversation."
        ),
    ),
    (
        "meeting-handoff",
        "Meeting handoff",
        "meeting_handoff",
        (
            "{{contact_person}} at {{company}} is ready for a meeting "
            "with Mark. Context: {{handoff_context}}. Suggested next "
            "step: {{next_action}}."
        ),
    ),
    (
        "objection-response",
        "Common-objection response",
        "objection_response",
        (
            "Hi {{contact_person}}, understood on {{objection}}. "
            "{{response_note}} Happy to revisit whenever the timing "
            "works better for {{company}}."
        ),
    ),
)


def _columns(db: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(
            "PRAGMA table_info(outreach_templates)"
        ).fetchall()
    }


def seed(db: sqlite3.Connection) -> None:
    organizations = db.execute(
        "SELECT id FROM organizations WHERE slug IN ('mark-agency', 'pendang')"
    ).fetchall()
    for organization in organizations:
        organization_id = int(organization["id"])
        for slug, title, category, body in SEED_TEMPLATES:
            db.execute(
                """
                INSERT OR IGNORE INTO outreach_templates (
                    organization_id, slug, title, category, body, approved
                )
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (organization_id, slug, title, category, body),
            )


def validate_schema(db: sqlite3.Connection) -> None:
    missing = REQUIRED_COLUMNS - _columns(db)
    if missing:
        raise RuntimeError(
            "Outreach template schema is incomplete: "
            + ", ".join(sorted(missing))
        )
