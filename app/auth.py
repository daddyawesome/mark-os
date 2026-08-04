from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from fastapi import Request

from app.database import get_db
from app.services.users import (
    authenticate_user,
    get_active_user_by_id,
    has_active_users,
)


SESSION_USER_ID_KEY = "mark_os_user_id"
SESSION_USER_KEY = SESSION_USER_ID_KEY

DEFAULT_SESSION_SECRET = "dev-only-change-this-secret-before-production"

IS_RAILWAY = bool(
    os.getenv("RAILWAY_ENVIRONMENT")
    or os.getenv("RAILWAY_PROJECT_ID")
)

SESSION_SECRET = os.getenv("SESSION_SECRET") or DEFAULT_SESSION_SECRET


def validate_session_secret(*, is_railway: bool, session_secret: str) -> None:
    """Reject the development cookie-signing secret in Railway environments."""
    clean_secret = (session_secret or "").strip()
    if is_railway and (
        not clean_secret or clean_secret == DEFAULT_SESSION_SECRET
    ):
        raise RuntimeError(
            "SESSION_SECRET must be set to a non-default value when running on Railway"
        )


def validate_auth_configuration() -> None:
    validate_session_secret(
        is_railway=IS_RAILWAY,
        session_secret=SESSION_SECRET,
    )


def credentials_configured() -> bool:
    """Return True when at least one active database user exists."""
    try:
        with get_db() as db:
            return has_active_users(db)
    except sqlite3.Error:
        return False


def authenticate_credentials(
    username: str,
    password: str,
) -> dict[str, Any] | None:
    """Authenticate against the hashed users table."""
    try:
        with get_db() as db:
            return authenticate_user(db, username, password)
    except sqlite3.Error:
        return None


def verify_credentials(username: str, password: str) -> bool:
    """Compatibility wrapper returning only the authentication result."""
    return authenticate_credentials(username, password) is not None


def sign_in(
    request: Request,
    user: Mapping[str, Any],
) -> None:
    """Start a clean session containing only the database user ID."""
    user_id = int(user["id"])
    if user_id <= 0:
        raise ValueError("Authenticated user ID must be positive.")

    request.session.clear()
    request.session[SESSION_USER_ID_KEY] = user_id


def sign_out(request: Request) -> None:
    """Remove all session data."""
    request.session.clear()


def current_user(request: Request) -> dict[str, Any] | None:
    """Return the current active user, rechecking SQLite every request."""
    raw_user_id = request.session.get(SESSION_USER_ID_KEY)
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return None

    if user_id <= 0:
        request.session.clear()
        return None

    try:
        with get_db() as db:
            user = get_active_user_by_id(db, user_id)
    except sqlite3.Error:
        return None

    if user is None:
        request.session.clear()
        return None

    return user


def is_authenticated(request: Request) -> bool:
    """Return True only for a currently active database user."""
    return current_user(request) is not None


def safe_next_path(next_path: str | None) -> str:
    """Allow only local paths for post-login redirects."""
    if not next_path:
        return "/"

    parsed = urlparse(next_path)

    if parsed.scheme or parsed.netloc:
        return "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/"

    return next_path
