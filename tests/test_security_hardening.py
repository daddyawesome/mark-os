from __future__ import annotations

import asyncio
import sqlite3

from fastapi import Request
from fastapi.responses import PlainTextResponse
from starlette.responses import Response

from app import auth, database
import app.main as main_module
from app.services.passwords import hash_password
from app.services.security import (
    apply_security_headers,
    is_cross_site_unsafe_request,
)
from app.services.team_users import (
    create_lead_sourcer,
    reset_user_password,
)
from app.services.users import authenticate_user


LEAD_SOURCER = {
    "id": 2,
    "username": "brother",
    "display_name": "Brother",
    "role": "lead_sourcer",
    "active": 1,
    "session_version": 1,
}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _session_request(session: dict | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "raw_path": b"/",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "session": session or {},
        }
    )


def _http_request(method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


def test_security_headers_protect_private_responses():
    response = apply_security_headers(
        Response(),
        secure_transport=True,
    )

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "max-age=31536000" in response.headers[
        "strict-transport-security"
    ]



def test_cross_site_browser_write_is_rejected():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/settings/users/2/password",
            "raw_path": b"/settings/users/2/password",
            "headers": [(b"sec-fetch-site", b"cross-site")],
            "query_string": b"",
            "scheme": "https",
            "server": ("example.test", 443),
            "client": ("testclient", 50000),
        }
    )
    assert is_cross_site_unsafe_request(request)


def test_same_origin_write_is_allowed_by_fetch_metadata_guard():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/settings/users/2/password",
            "raw_path": b"/settings/users/2/password",
            "headers": [(b"sec-fetch-site", b"same-origin")],
            "query_string": b"",
            "scheme": "https",
            "server": ("example.test", 443),
            "client": ("testclient", 50000),
        }
    )
    assert not is_cross_site_unsafe_request(request)


def test_same_site_cross_origin_write_is_rejected():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/settings/users/2/password",
            "raw_path": b"/settings/users/2/password",
            "headers": [(b"sec-fetch-site", b"same-site")],
            "query_string": b"",
            "scheme": "https",
            "server": ("example.test", 443),
            "client": ("testclient", 50000),
        }
    )
    assert is_cross_site_unsafe_request(request)

def test_password_reset_invalidates_existing_signed_session(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "session-revocation.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        sourcer = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        user = authenticate_user(
            db,
            "brother",
            "temporary-pass-123",
        )

    request = _session_request()
    auth.sign_in(request, user)
    assert auth.current_user(request)["id"] == sourcer["id"]

    with database.get_db() as db:
        reset_user_password(
            db,
            target_user_id=sourcer["id"],
            password="replacement-pass-456",
            password_confirmation="replacement-pass-456",
        )

    assert auth.current_user(request) is None
    assert request.session == {}


def test_lead_sourcer_cannot_open_or_post_user_management(
    monkeypatch,
):
    monkeypatch.setattr(
        main_module,
        "current_user",
        lambda request: LEAD_SOURCER,
    )

    async def call_next(request):
        return PlainTextResponse("should not run")

    get_response = asyncio.run(
        main_module.login_and_permission_guard(
            _http_request("GET", "/settings/users"),
            call_next,
        )
    )
    post_response = asyncio.run(
        main_module.login_and_permission_guard(
            _http_request(
                "POST",
                "/settings/users/2/password",
            ),
            call_next,
        )
    )

    assert get_response.status_code == 303
    assert get_response.headers["location"] == "/crm?error=forbidden"
    assert post_response.status_code == 403


def test_existing_user_schema_is_backfilled_with_session_version(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "prior-user-schema.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.delenv("MARK_OS_PASSWORD", raising=False)
    database.init_db()

    with database.get_db() as db:
        db.execute("DROP TABLE users")
        db.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE
                    CHECK(length(trim(username)) > 0),
                display_name TEXT NOT NULL
                    CHECK(length(trim(display_name)) > 0),
                password_hash TEXT NOT NULL
                    CHECK(length(trim(password_hash)) > 0),
                role TEXT NOT NULL DEFAULT 'lead_sourcer'
                    CHECK(role IN ('owner', 'lead_sourcer')),
                active INTEGER NOT NULL DEFAULT 1
                    CHECK(active IN (0, 1)),
                must_change_password INTEGER NOT NULL DEFAULT 0
                    CHECK(must_change_password IN (0, 1)),
                last_login_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        db.execute(
            """
            INSERT INTO users (
                username,
                display_name,
                password_hash,
                role
            )
            VALUES (?, ?, ?, 'owner')
            """,
            (
                "mark",
                "Mark",
                hash_password("owner-password-123"),
            ),
        )

    database.init_db()

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    }
    user = connection.execute(
        "SELECT session_version FROM users WHERE username = 'mark'"
    ).fetchone()
    connection.close()

    assert "session_version" in columns
    assert user["session_version"] == 1
