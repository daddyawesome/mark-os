from __future__ import annotations

from starlette.requests import Request

from app import auth, database
from app.services.users import authenticate_user


def _request_with_session(session: dict | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "session": session or {},
        }
    )


def test_database_authentication_updates_last_login(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "database-auth.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")
    database.init_db()

    with database.get_db() as db:
        before = db.execute(
            "SELECT last_login_at FROM users WHERE username = 'mark'"
        ).fetchone()["last_login_at"]
        user = authenticate_user(db, "MARK", "owner-password")

    assert user is not None
    assert user["username"] == "mark"
    assert user["role"] == "owner"
    assert user["last_login_at"] is not None
    assert before is None


def test_wrong_unknown_and_inactive_accounts_cannot_authenticate(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "rejected-auth.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password")
    database.init_db()

    with database.get_db() as db:
        assert authenticate_user(db, "mark", "wrong-password") is None
        assert authenticate_user(db, "unknown", "owner-password") is None

        db.execute(
            "UPDATE users SET active = 0 WHERE username = 'mark'"
        )
        assert authenticate_user(db, "mark", "owner-password") is None


def test_session_contains_only_user_id_and_rechecks_active_status(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "session-auth.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password")
    database.init_db()

    with database.get_db() as db:
        user = authenticate_user(db, "mark", "owner-password")

    request = _request_with_session()
    auth.sign_in(request, user)

    assert request.session[auth.SESSION_USER_ID_KEY] == user["id"]
    assert request.session[auth.SESSION_VERSION_KEY] == user["session_version"]
    assert len(request.session[auth.SESSION_TOKEN_KEY]) >= 32
    assert auth.is_authenticated(request)
    assert auth.current_user(request)["username"] == "mark"

    with database.get_db() as db:
        db.execute(
            "UPDATE users SET active = 0 WHERE id = ?",
            (user["id"],),
        )

    assert not auth.is_authenticated(request)
    assert request.session == {}


def test_legacy_username_only_session_is_not_authenticated(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "legacy-session.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password")
    database.init_db()

    request = _request_with_session({"mark_os_user": "mark"})
    assert not auth.is_authenticated(request)
