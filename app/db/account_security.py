from __future__ import annotations

import sqlite3


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS auth_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE
        CHECK(length(token_hash) = 64),
    session_version INTEGER NOT NULL
        CHECK(session_version >= 1),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier_hash TEXT NOT NULL
        CHECK(length(identifier_hash) = 64),
    attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS security_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL CHECK(length(trim(event_type)) > 0),
    actor_user_id INTEGER,
    target_user_id INTEGER,
    subject_type TEXT NOT NULL CHECK(length(trim(subject_type)) > 0),
    subject_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY(target_user_id) REFERENCES users(id) ON DELETE SET NULL
);
"""


INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_active
ON auth_sessions(user_id, revoked_at, expires_at);

CREATE INDEX IF NOT EXISTS idx_login_attempts_identifier_time
ON login_attempts(identifier_hash, attempted_at);

CREATE INDEX IF NOT EXISTS idx_security_audit_events_time
ON security_audit_events(occurred_at, id);

CREATE INDEX IF NOT EXISTS idx_security_audit_events_target
ON security_audit_events(target_user_id, occurred_at, id);

CREATE TRIGGER IF NOT EXISTS trg_users_role_change_audit
AFTER UPDATE OF role ON users
WHEN OLD.role <> NEW.role
BEGIN
    INSERT INTO security_audit_events (
        event_type, target_user_id, subject_type, subject_id, details_json
    ) VALUES (
        'role_changed', NEW.id, 'user', CAST(NEW.id AS TEXT),
        '{"from":"' || OLD.role || '","to":"' || NEW.role || '"}'
    );
END;
"""


def validate_schema(db: sqlite3.Connection) -> None:
    required = {
        "auth_sessions": {
            "id", "user_id", "token_hash", "session_version", "created_at",
            "last_seen_at", "expires_at", "revoked_at",
        },
        "login_attempts": {"id", "identifier_hash", "attempted_at"},
        "security_audit_events": {
            "id", "event_type", "actor_user_id", "target_user_id",
            "subject_type", "subject_id", "details_json", "occurred_at",
        },
    }
    for table, expected in required.items():
        columns = {
            row["name"] for row in db.execute(f"PRAGMA table_info({table})")
        }
        missing = expected - columns
        if missing:
            raise RuntimeError(
                f"Incompatible {table} schema; missing columns: "
                + ", ".join(sorted(missing))
            )


def validate_indexes(db: sqlite3.Connection) -> None:
    required_indexes = {
        "idx_auth_sessions_user_active",
        "idx_login_attempts_identifier_time",
        "idx_security_audit_events_time",
        "idx_security_audit_events_target",
    }
    indexes = {
        str(row["name"])
        for table in ("auth_sessions", "login_attempts", "security_audit_events")
        for row in db.execute(f"PRAGMA index_list({table})")
    }
    missing = required_indexes - indexes
    if missing:
        raise RuntimeError(
            "Missing account-security indexes: " + ", ".join(sorted(missing))
        )
    trigger = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = 'trg_users_role_change_audit'"
    ).fetchone()
    if trigger is None:
        raise RuntimeError("Missing role-change audit trigger")
