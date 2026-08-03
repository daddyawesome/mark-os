from __future__ import annotations

import asyncio
import sqlite3
from collections import Counter
from urllib.parse import urlencode, urlsplit

from fastapi.routing import APIRoute
from starlette.routing import Mount

import app.auth as auth
from app import database
from app.main import app


EXPECTED_ROUTES = [
    ("GET", "/login", "login_page"),
    ("POST", "/login", "login_submit"),
    ("POST", "/logout", "logout"),
    ("GET", "/", "home"),
    ("POST", "/check-in", "create_checkin"),
    ("GET", "/quests", "quests"),
    ("POST", "/quests", "create_quest"),
    ("GET", "/quests/{quest_id}", "quest_detail"),
    ("POST", "/quests/{quest_id}/start", "start_quest"),
    ("POST", "/quests/{quest_id}/block", "block_quest"),
    ("POST", "/quests/{quest_id}/unblock", "unblock_quest"),
    ("POST", "/quests/{quest_id}/abandon", "abandon_quest"),
    ("POST", "/quests/{quest_id}/update", "update_quest"),
    ("POST", "/quests/{quest_id}/complete", "complete_quest"),
    ("GET", "/history/{checkin_id}/edit", "edit_checkin_page"),
    ("POST", "/history/{checkin_id}/edit", "edit_checkin_submit"),
    ("POST", "/history/{checkin_id}/delete", "delete_checkin"),
    ("GET", "/history", "history"),
    ("GET", "/life-os", "life_os"),
    ("GET", "/goals", "goals_page"),
    ("POST", "/goals", "create_goal"),
    ("POST", "/projects/{project_id}/link-goal", "link_project_goal"),
    ("GET", "/health", "health"),
]


def _application_routes() -> tuple[list[tuple[str, str, str]], int]:
    found = []
    handler_count = 0
    pending = list(app.routes)
    while pending:
        route = pending.pop()
        if isinstance(route, APIRoute):
            handler_count += 1
            found.extend((method, route.path, route.name) for method in route.methods)
        elif hasattr(route, "original_router"):
            pending.extend(route.original_router.routes)
    return found, handler_count


async def _request(
    target: str,
    *,
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
):
    parsed = urlsplit(target)
    messages = []
    request_sent = False
    response_complete = asyncio.Event()

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await response_complete.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get(
            "more_body", False
        ):
            response_complete.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode(),
        "query_string": parsed.query.encode(),
        "root_path": "",
        "headers": headers or [],
        "client": ("test-client", 50000),
        "server": ("test-server", 80),
    }
    await app(scope, receive, send)

    start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return start["status"], start["headers"], response_body


def _header_values(headers, name: bytes) -> list[bytes]:
    return [value for key, value in headers if key.lower() == name.lower()]


def _login_cookie(monkeypatch) -> tuple[bytes, bytes]:
    monkeypatch.setattr(auth, "USERNAME", "test-user")
    monkeypatch.setattr(auth, "PASSWORD", "test-password")
    body = urlencode(
        {
            "username": "test-user",
            "password": "test-password",
            "next": "/",
        }
    ).encode()
    status, headers, _ = asyncio.run(
        _request(
            "/login",
            method="POST",
            headers=[
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", str(len(body)).encode()),
            ],
            body=body,
        )
    )

    assert status == 303
    assert _header_values(headers, b"location") == [b"/"]
    set_cookie = _header_values(headers, b"set-cookie")[0]
    return set_cookie.split(b";", 1)[0], set_cookie


def _post_form(
    target: str,
    data: dict[str, str],
    *,
    cookie: bytes,
):
    body = urlencode(data).encode()
    return asyncio.run(
        _request(
            target,
            method="POST",
            headers=[
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", str(len(body)).encode()),
                (b"cookie", cookie),
            ],
            body=body,
        )
    )


async def _drive_lifespan():
    incoming = asyncio.Queue()
    await incoming.put({"type": "lifespan.startup"})
    await incoming.put({"type": "lifespan.shutdown"})
    messages = []

    async def receive():
        return await incoming.get()

    async def send(message):
        messages.append(message)

    error = None
    try:
        await app(
            {
                "type": "lifespan",
                "asgi": {"version": "3.0", "spec_version": "2.0"},
                "state": {},
            },
            receive,
            send,
        )
    except Exception as exc:
        error = exc
    return messages, error


def test_lifespan_initializes_temporary_database(tmp_path, monkeypatch):
    database_path = tmp_path / "lifespan.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setattr(auth, "IS_RAILWAY", False)

    messages, error = asyncio.run(_drive_lifespan())

    assert error is None
    assert [message["type"] for message in messages] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]
    assert database_path.exists()
    with sqlite3.connect(database_path) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"profile", "tasks", "chat_sessions", "chat_messages"} <= tables


def test_lifespan_rejects_default_secret_on_railway_before_database_access(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "must-not-exist.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.setattr(auth, "IS_RAILWAY", True)
    monkeypatch.setattr(auth, "SESSION_SECRET", auth.DEFAULT_SESSION_SECRET)

    messages, error = asyncio.run(_drive_lifespan())

    assert isinstance(error, RuntimeError)
    assert "SESSION_SECRET" in str(error)
    assert [message["type"] for message in messages] == [
        "lifespan.startup.failed"
    ]
    assert not database_path.exists()


def test_all_routes_and_static_mount_are_preserved():
    routes, handler_count = _application_routes()
    assert Counter(routes) == Counter(EXPECTED_ROUTES)
    assert len(routes) == len(EXPECTED_ROUTES)
    assert handler_count == len(EXPECTED_ROUTES)
    assert any(
        isinstance(route, Mount) and route.path == "/static" and route.name == "static"
        for route in app.routes
    )


def test_public_health_static_and_protected_home_behavior():
    health_status, _, health_body = asyncio.run(_request("/health"))
    home_status, home_headers, _ = asyncio.run(_request("/"))
    static_status, _, _ = asyncio.run(_request("/static/quests.css"))

    assert health_status == 200
    assert health_body == b'{"status":"ok","version":"0.2.2-phase4-revised"}'
    assert home_status == 303
    assert _header_values(home_headers, b"location") == [b"/login?next=/"]
    assert static_status == 200


def test_login_cookie_round_trip(monkeypatch):
    cookie, set_cookie = _login_cookie(monkeypatch)
    authenticated_status, authenticated_headers, _ = asyncio.run(
        _request("/login", headers=[(b"cookie", cookie)])
    )

    assert authenticated_status == 303
    assert _header_values(authenticated_headers, b"location") == [b"/"]
    normalized_cookie = set_cookie.lower()
    assert normalized_cookie.startswith(b"mark_os_session=")
    assert b"httponly" in normalized_cookie
    assert b"samesite=lax" in normalized_cookie
    assert b"max-age=2592000" in normalized_cookie


def test_authenticated_pages_render_with_temporary_database(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "application.db")
    database.init_db()
    cookie, _ = _login_cookie(monkeypatch)

    for target in ("/", "/quests", "/quests/1", "/goals", "/life-os", "/history"):
        status, _, _ = asyncio.run(_request(target, headers=[(b"cookie", cookie)]))
        assert status == 200, target


def test_representative_post_routes_persist_to_temporary_database(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "post-routes.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()
    cookie, _ = _login_cookie(monkeypatch)

    checkin_status, checkin_headers, _ = _post_form(
        "/check-in",
        {
            "cash_in": "100",
            "expenses": "20",
            "free_hours": "2",
            "energy": "4",
            "accomplished": "Split the application routes",
        },
        cookie=cookie,
    )
    quest_status, quest_headers, _ = _post_form(
        "/quests",
        {
            "title": "Verify router refactor",
            "description": "Exercise the new quests router",
            "difficulty": "normal",
            "priority": "7",
        },
        cookie=cookie,
    )
    goal_status, goal_headers, _ = _post_form(
        "/goals",
        {
            "title": "Keep MARK OS maintainable",
            "category": "engineering",
            "priority": "8",
        },
        cookie=cookie,
    )

    assert (checkin_status, _header_values(checkin_headers, b"location")) == (
        303,
        [b"/"],
    )
    assert (quest_status, _header_values(quest_headers, b"location")) == (
        303,
        [b"/quests"],
    )
    assert (goal_status, _header_values(goal_headers, b"location")) == (
        303,
        [b"/goals"],
    )

    with database.get_db() as db:
        checkin = db.execute(
            "SELECT cash, cash_in, expenses, energy FROM checkins ORDER BY id DESC LIMIT 1"
        ).fetchone()
        direction_count = db.execute(
            "SELECT COUNT(*) FROM directions WHERE checkin_id = (SELECT MAX(id) FROM checkins)"
        ).fetchone()[0]
        quest = db.execute(
            "SELECT status, priority FROM tasks WHERE title = ?",
            ("Verify router refactor",),
        ).fetchone()
        goal = db.execute(
            "SELECT category, priority FROM goals WHERE title = ?",
            ("Keep MARK OS maintainable",),
        ).fetchone()

    assert tuple(checkin) == (80.0, 100.0, 20.0, 4)
    assert direction_count == 1
    assert tuple(quest) == ("backlog", 7)
    assert tuple(goal) == ("engineering", 8)
