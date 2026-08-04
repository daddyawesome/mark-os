from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from fastapi import Request


_REQUEST_USER_ID: ContextVar[int | None] = ContextVar(
    "mark_os_personal_user_id",
    default=None,
)

PERSONAL_ROLES = {"owner", "member"}
LEGACY_UNOWNED_USER_ID = 0


def positive_user_id(value: int) -> int:
    if isinstance(value, bool):
        raise ValueError("User ID must be a positive integer.")
    try:
        user_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("User ID must be a positive integer.") from exc
    if user_id <= 0:
        raise ValueError("User ID must be a positive integer.")
    return user_id


def bind_request_user(user_id: int) -> Token:
    return _REQUEST_USER_ID.set(positive_user_id(user_id))


def reset_request_user(token: Token) -> None:
    _REQUEST_USER_ID.reset(token)


@contextmanager
def user_scope(user_id: int) -> Iterator[None]:
    token = bind_request_user(user_id)
    try:
        yield
    finally:
        reset_request_user(token)


def request_user_id(request: Request) -> int:
    user = getattr(request.state, "current_user", None)
    if not user:
        raise RuntimeError("Authenticated user context is unavailable.")
    return positive_user_id(user["id"])


def resolve_user_id(
    db: sqlite3.Connection,
    explicit_user_id: int | None = None,
) -> int:
    """Resolve one owner/member for a personal operation.

    Authenticated production requests carry a real user through request
    context. Legacy migrations and isolated unit-test databases may have no
    users table or no bootstrapped owner; those temporarily use marker 0.
    """
    candidate = (
        explicit_user_id
        if explicit_user_id is not None
        else _REQUEST_USER_ID.get()
    )

    users_table = db.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'users'
        """
    ).fetchone()

    if candidate is None:
        if users_table is None:
            return LEGACY_UNOWNED_USER_ID

        row = db.execute(
            """
            SELECT id
            FROM users
            WHERE role = 'owner' AND active = 1
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return LEGACY_UNOWNED_USER_ID
        candidate = int(row["id"])

    user_id = int(candidate)
    if user_id == LEGACY_UNOWNED_USER_ID:
        return user_id

    user_id = positive_user_id(user_id)
    if users_table is None:
        return user_id

    row = db.execute(
        """
        SELECT id, role, active
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    if (
        row is None
        or row["active"] != 1
        or row["role"] not in PERSONAL_ROLES
    ):
        raise PermissionError(
            "Personal MARK-OS data requires an active owner or member."
        )
    return user_id
