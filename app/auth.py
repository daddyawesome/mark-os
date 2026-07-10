from __future__ import annotations

import hashlib
import os
import secrets
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse

SESSION_USER_KEY = "mark_os_user"
USERNAME = os.getenv("MARK_OS_USERNAME", "mark")
PASSWORD = os.getenv("MARK_OS_PASSWORD", "")

# Prefer an explicit random secret. If it is missing, derive a stable fallback from the
# configured password so sessions survive restarts. The app still refuses login when no
# password is configured.
SESSION_SECRET = os.getenv("MARK_OS_SECRET_KEY") or hashlib.sha256(
    f"mark-os-session:{PASSWORD or 'password-not-configured'}".encode("utf-8")
).hexdigest()

IS_RAILWAY = bool(
    os.getenv("RAILWAY_ENVIRONMENT")
    or os.getenv("RAILWAY_PROJECT_ID")
    or os.getenv("RAILWAY_SERVICE_ID")
)


def credentials_configured() -> bool:
    return bool(PASSWORD)


def verify_credentials(username: str, password: str) -> bool:
    if not credentials_configured():
        return False
    return secrets.compare_digest(username, USERNAME) and secrets.compare_digest(
        password, PASSWORD
    )


def is_authenticated(request: Request) -> bool:
    return request.session.get(SESSION_USER_KEY) == USERNAME


def sign_in(request: Request) -> None:
    request.session.clear()
    request.session[SESSION_USER_KEY] = USERNAME


def sign_out(request: Request) -> None:
    request.session.clear()


def safe_next_path(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def login_redirect(path: str = "/") -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={quote(path)}", status_code=303)
