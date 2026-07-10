from __future__ import annotations

import hmac
import os
from urllib.parse import urlparse

from fastapi import Request

SESSION_USER_KEY = "mark_os_user"
USERNAME = os.getenv("MARK_OS_USERNAME", "mark")

IS_RAILWAY = bool(
    os.getenv("RAILWAY_ENVIRONMENT")
    or os.getenv("RAILWAY_PROJECT_ID")
)

SESSION_SECRET = os.getenv(
    "SESSION_SECRET",
    "dev-only-change-this-secret-before-production",
)

PASSWORD = os.getenv("MARK_OS_PASSWORD", "")


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
