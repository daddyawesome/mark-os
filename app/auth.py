from __future__ import annotations

import hmac
import os
from urllib.parse import urlparse

from fastapi import Request

SESSION_USER_KEY = "mark_os_user"
USERNAME = os.getenv("MARK_OS_USERNAME", "mark")
DEFAULT_SESSION_SECRET = "dev-only-change-this-secret-before-production"

IS_RAILWAY = bool(
    os.getenv("RAILWAY_ENVIRONMENT")
    or os.getenv("RAILWAY_PROJECT_ID")
)

SESSION_SECRET = os.getenv("SESSION_SECRET") or DEFAULT_SESSION_SECRET

PASSWORD = os.getenv("MARK_OS_PASSWORD", "")


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
    """Return True when a login password has been configured."""
    return bool(PASSWORD)


def verify_credentials(username: str, password: str) -> bool:
    """Safely verify the submitted username and password."""
    if not credentials_configured():
        return False

    username_matches = hmac.compare_digest(username, USERNAME)
    password_matches = hmac.compare_digest(password, PASSWORD)

    return username_matches and password_matches


def sign_in(request: Request) -> None:
    """Store the authenticated user in the signed session cookie."""
    request.session[SESSION_USER_KEY] = USERNAME


def sign_out(request: Request) -> None:
    """Remove all session data."""
    request.session.clear()


def is_authenticated(request: Request) -> bool:
    """Return True when the session belongs to the configured user."""
    return request.session.get(SESSION_USER_KEY) == USERNAME


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
