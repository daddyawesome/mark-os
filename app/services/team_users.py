from __future__ import annotations

import sqlite3
from typing import Any

from app.services.passwords import hash_password


MAX_USERNAME_LENGTH = 50
MAX_DISPLAY_NAME_LENGTH = 100
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200


def _required_text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = " ".join(value.strip().split())
    if not clean:
        raise ValueError(f"{field_name} is required.")
    if len(clean) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer.")
    return clean


def get_primary_owner_id(db: sqlite3.Connection) -> int | None:
    row = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner'
        ORDER BY active DESC, id
        LIMIT 1
        """
    ).fetchone()
    return int(row["id"]) if row is not None else None


def create_lead_sourcer(
    db: sqlite3.Connection,
    *,
    username: str,
    display_name: str,
    password: str,
    password_confirmation: str,
) -> dict[str, Any]:
    clean_username = _required_text(
        username,
        "Username",
        MAX_USERNAME_LENGTH,
    )
    clean_display_name = _required_text(
        display_name,
        "Display name",
        MAX_DISPLAY_NAME_LENGTH,
    )

    if not isinstance(password, str):
        raise ValueError("Password must be text.")
    if password != password_confirmation:
        raise ValueError("Password confirmation does not match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be {MAX_PASSWORD_LENGTH} characters or fewer."
        )

    try:
        cursor = db.execute(
            """
            INSERT INTO users (
                username,
                display_name,
                password_hash,
                role,
                active,
                must_change_password
            )
            VALUES (?, ?, ?, 'lead_sourcer', 1, 0)
            """,
            (
                clean_username,
                clean_display_name,
                hash_password(password),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("That username is already in use.") from exc

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
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Created user could not be reloaded.")
    return dict(row)
