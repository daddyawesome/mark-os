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
from app.services.account_security import (
    create_session,
    revoke_session,
    validate_session,
)
from app.services.workspace_context import (
    resolve_workspace_session,
    workspace_display_role,
)


SESSION_USER_ID_KEY = "mark_os_user_id"
SESSION_VERSION_KEY = "mark_os_session_version"
SESSION_TOKEN_KEY = "mark_os_session_token"
SESSION_USER_KEY = SESSION_USER_ID_KEY

DEFAULT_SESSION_SECRET = "dev-only-change-this-secret-before-production"

IS_RAILWAY = bool(
    os.getenv("RAILWAY_ENVIRONMENT")
    or os.getenv("RAILWAY_PROJECT_ID")
)

SESSION_SECRET = os.getenv("SESSION_SECRET") or DEFAULT_SESSION_SECRET


def validate_session_secret(*, is_railway: bool, session_secret: str) -> None:
    clean_secret = (session_secret or "").strip()
    if is_railway and (
        not clean_secret or clean_secret == DEFAULT_SESSION_SECRET
    ):
        raise RuntimeError(
            "SESSION_SECRET must be set to a non-default value "
            "when running on Railway"
        )


def validate_auth_configuration() -> None:
    validate_session_secret(
        is_railway=IS_RAILWAY,
        session_secret=SESSION_SECRET,
    )


def credentials_configured() -> bool:
    try:
        with get_db() as db:
            return has_active_users(db)
    except sqlite3.Error:
        return False


def authenticate_credentials(
    username: str,
    password: str,
) -> dict[str, Any] | None:
    try:
        with get_db() as db:
            return authenticate_user(db, username, password)
    except sqlite3.Error:
        return None


def verify_credentials(username: str, password: str) -> bool:
    return authenticate_credentials(username, password) is not None


def sign_in(
    request: Request,
    user: Mapping[str, Any],
) -> None:
    user_id = int(user["id"])
    session_version = int(user["session_version"])
    if user_id <= 0 or session_version <= 0:
        raise ValueError(
            "Authenticated user ID and session version must be positive."
        )

    with get_db() as db:
        token = create_session(
            db,
            user_id=user_id,
            session_version=session_version,
        )

    request.session.clear()
    request.session[SESSION_USER_ID_KEY] = user_id
    request.session[SESSION_VERSION_KEY] = session_version
    request.session[SESSION_TOKEN_KEY] = token


def sign_out(request: Request) -> None:
    raw_user_id = request.session.get(SESSION_USER_ID_KEY)
    token = request.session.get(SESSION_TOKEN_KEY)
    try:
        user_id = int(raw_user_id)
        if isinstance(token, str):
            with get_db() as db:
                revoke_session(db, token=token, user_id=user_id)
    except (TypeError, ValueError, sqlite3.Error):
        pass
    request.session.clear()


def current_user(request: Request) -> dict[str, Any] | None:
    raw_user_id = request.session.get(SESSION_USER_ID_KEY)
    raw_session_version = request.session.get(SESSION_VERSION_KEY)
    raw_session_token = request.session.get(SESSION_TOKEN_KEY)

    try:
        user_id = int(raw_user_id)
        session_version = int(raw_session_version)
    except (TypeError, ValueError):
        request.session.clear()
        return None

    if (
        user_id <= 0
        or session_version <= 0
        or not isinstance(raw_session_token, str)
    ):
        request.session.clear()
        return None

    try:
        with get_db() as db:
            user = get_active_user_by_id(db, user_id)
            if (
                user is None
                or int(user["session_version"]) != session_version
            ):
                request.session.clear()
                return None

            session_id = validate_session(
                db,
                token=raw_session_token,
                user_id=user_id,
                session_version=session_version,
            )
            if session_id is None:
                request.session.clear()
                return None

            current_workspace, authorized = resolve_workspace_session(
                db,
                request.session,
                user,
            )
    except sqlite3.Error:
        return None

    user["current_workspace"] = current_workspace
    user["authorized_workspaces"] = authorized
    user["workspace_display_role"] = workspace_display_role(user)
    user["current_session_id"] = session_id
    return user


def is_authenticated(request: Request) -> bool:
    return current_user(request) is not None


def safe_next_path(next_path: str | None) -> str:
    if not next_path:
        return "/"

    parsed = urlparse(next_path)

    if parsed.scheme or parsed.netloc:
        return "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/"

    return next_path
