from __future__ import annotations

import sqlite3
from typing import Any

from app.services.passwords import verify_password


_DUMMY_PASSWORD_HASH = "pbkdf2_sha256$600000$bWFyay1vcy1tMi1kdW1teQ$nZ1u_kGXiqMoM09R-UqhaPWhd2oDettqRnbUtI84ZUg"


def _clean_username(username: str) -> str:
    if not isinstance(username, str):
        return ""
    return username.strip()


def has_active_users(db: sqlite3.Connection) -> bool:
    row = db.execute(
        "SELECT 1 FROM users WHERE active = 1 LIMIT 1"
    ).fetchone()
    return row is not None


def get_active_user_by_id(
    db: sqlite3.Connection,
    user_id: int,
) -> dict[str, Any] | None:
    row = db.execute(
        """
        SELECT
            id,
            username,
            display_name,
            role,
            active,
            must_change_password,
            last_login_at,
            created_at,
            updated_at
        FROM users
        WHERE id = ? AND active = 1
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def authenticate_user(
    db: sqlite3.Connection,
    username: str,
    password: str,
) -> dict[str, Any] | None:
    """Authenticate one active database user and record a successful login."""
    clean_username = _clean_username(username)
    if not clean_username or not isinstance(password, str) or not password:
        verify_password(
            password if isinstance(password, str) else "",
            _DUMMY_PASSWORD_HASH,
        )
        return None

    row = db.execute(
        """
        SELECT
            id,
            username,
            display_name,
            password_hash,
            role,
            active,
            must_change_password,
            last_login_at,
            created_at,
            updated_at
        FROM users
        WHERE username = ? COLLATE NOCASE
        LIMIT 1
        """,
        (clean_username,),
    ).fetchone()

    stored_hash = (
        row["password_hash"]
        if row is not None
        else _DUMMY_PASSWORD_HASH
    )
    password_matches = verify_password(password, stored_hash)

    if row is None or not password_matches or row["active"] != 1:
        return None

    db.execute(
        """
        UPDATE users
        SET
            last_login_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (row["id"],),
    )

    authenticated = db.execute(
        """
        SELECT
            id,
            username,
            display_name,
            role,
            active,
            must_change_password,
            last_login_at,
            created_at,
            updated_at
        FROM users
        WHERE id = ?
        """,
        (row["id"],),
    ).fetchone()
    return dict(authenticated)
