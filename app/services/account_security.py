from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


SESSION_LIFETIME = timedelta(days=7)
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_FAILURE_LIMIT = 5


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def login_identifier(secret: str, username: str, client_host: str | None) -> str:
    normalized = f"{username.strip().casefold()}\0{(client_host or '').strip()}"
    return hmac.new(
        secret.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def is_login_rate_limited(
    db: sqlite3.Connection,
    identifier_hash: str,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    cutoff = _utc_timestamp(current - LOGIN_WINDOW)
    row = db.execute(
        """
        SELECT COUNT(*) AS failure_count
        FROM login_attempts
        WHERE identifier_hash = ? AND attempted_at >= ?
        """,
        (identifier_hash, cutoff),
    ).fetchone()
    return int(row["failure_count"]) >= LOGIN_FAILURE_LIMIT


def record_failed_login(
    db: sqlite3.Connection,
    identifier_hash: str,
    *,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(timezone.utc)
    db.execute(
        "INSERT INTO login_attempts (identifier_hash, attempted_at) VALUES (?, ?)",
        (identifier_hash, _utc_timestamp(current)),
    )
    db.execute(
        "DELETE FROM login_attempts WHERE attempted_at < ?",
        (_utc_timestamp(current - timedelta(days=1)),),
    )
    record_audit_event(
        db,
        event_type="authentication_failed",
        subject_type="authentication",
    )


def clear_failed_logins(db: sqlite3.Connection, identifier_hash: str) -> None:
    db.execute(
        "DELETE FROM login_attempts WHERE identifier_hash = ?",
        (identifier_hash,),
    )


def create_session(
    db: sqlite3.Connection,
    *,
    user_id: int,
    session_version: int,
    now: datetime | None = None,
) -> str:
    current = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    db.execute(
        """
        INSERT INTO auth_sessions (
            user_id, token_hash, session_version, created_at, last_seen_at,
            expires_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            _token_hash(token),
            session_version,
            _utc_timestamp(current),
            _utc_timestamp(current),
            _utc_timestamp(current + SESSION_LIFETIME),
        ),
    )
    return token


def validate_session(
    db: sqlite3.Connection,
    *,
    token: str,
    user_id: int,
    session_version: int,
    now: datetime | None = None,
) -> int | None:
    if not isinstance(token, str) or len(token) < 32 or len(token) > 128:
        return None
    current = now or datetime.now(timezone.utc)
    row = db.execute(
        """
        SELECT id, last_seen_at
        FROM auth_sessions
        WHERE token_hash = ?
          AND user_id = ?
          AND session_version = ?
          AND revoked_at IS NULL
          AND expires_at > ?
        """,
        (_token_hash(token), user_id, session_version, _utc_timestamp(current)),
    ).fetchone()
    if row is None:
        return None
    last_seen = datetime.fromisoformat(str(row["last_seen_at"])).replace(
        tzinfo=timezone.utc
    )
    if current - last_seen >= timedelta(minutes=5):
        db.execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?",
            (_utc_timestamp(current), row["id"]),
        )
    return int(row["id"])


def revoke_session(db: sqlite3.Connection, *, token: str, user_id: int) -> None:
    if not isinstance(token, str) or not token:
        return
    db.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
        WHERE token_hash = ? AND user_id = ?
        """,
        (_token_hash(token), user_id),
    )


def revoke_all_sessions(
    db: sqlite3.Connection,
    *,
    user_id: int,
    except_session_id: int | None = None,
) -> int:
    if except_session_id is None:
        cursor = db.execute(
            """
            UPDATE auth_sessions
            SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
            WHERE user_id = ? AND revoked_at IS NULL
            """,
            (user_id,),
        )
    else:
        cursor = db.execute(
            """
            UPDATE auth_sessions
            SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
            WHERE user_id = ? AND id != ? AND revoked_at IS NULL
            """,
            (user_id, except_session_id),
        )
    return int(cursor.rowcount)


def list_active_sessions(
    db: sqlite3.Connection,
    *,
    user_id: int,
    current_session_id: int | None,
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT id, created_at, last_seen_at, expires_at
        FROM auth_sessions
        WHERE user_id = ?
          AND revoked_at IS NULL
          AND expires_at > CURRENT_TIMESTAMP
        ORDER BY last_seen_at DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    return [
        {**dict(row), "is_current": int(row["id"]) == current_session_id}
        for row in rows
    ]


def record_audit_event(
    db: sqlite3.Connection,
    *,
    event_type: str,
    subject_type: str,
    actor_user_id: int | None = None,
    target_user_id: int | None = None,
    subject_id: str | int | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    safe_details = {
        str(key): value
        for key, value in (details or {}).items()
        if isinstance(value, (str, int, bool)) or value is None
    }
    db.execute(
        """
        INSERT INTO security_audit_events (
            event_type, actor_user_id, target_user_id, subject_type,
            subject_id, details_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            actor_user_id,
            target_user_id,
            subject_type,
            str(subject_id) if subject_id is not None else None,
            json.dumps(safe_details, sort_keys=True, separators=(",", ":")),
        ),
    )


def list_recent_audit_events(
    db: sqlite3.Connection, *, limit: int = 100
) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit), 1), 200)
    rows = db.execute(
        """
        SELECT e.id, e.event_type, e.subject_type, e.subject_id,
               e.details_json, e.occurred_at,
               actor.display_name AS actor_name,
               target.display_name AS target_name
        FROM security_audit_events AS e
        LEFT JOIN users AS actor ON actor.id = e.actor_user_id
        LEFT JOIN users AS target ON target.id = e.target_user_id
        ORDER BY e.occurred_at DESC, e.id DESC
        LIMIT ?
        """,
        (safe_limit,),
    ).fetchall()
    return [dict(row) for row in rows]
