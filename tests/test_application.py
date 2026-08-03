from __future__ import annotations

import asyncio
import sqlite3
from collections import Counter
from pathlib import Path
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
    ("GET", "/crm", "crm_dashboard"),
    ("POST", "/crm/leads", "create_lead"),
    ("GET", "/crm/leads/{lead_id}", "lead_detail"),
    ("GET", "/crm/leads/{lead_id}/edit", "edit_lead_page"),
    ("POST", "/crm/leads/{lead_id}/edit", "edit_lead"),
    ("POST", "/crm/leads/{lead_id}/pipeline", "update_pipeline"),
    ("POST", "/crm/leads/{lead_id}/next-action", "update_next_action"),
    ("GET", "/crm/leads/{lead_id}/delete", "delete_lead_page"),
    ("POST", "/crm/leads/{lead_id}/delete", "delete_lead"),
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
    assert {
        "profile",
        "tasks",
        "chat_sessions",
        "chat_messages",
        "agent_runs",
        "agent_steps",
        "leads",
    } <= tables


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
    assert app.version == "0.3.0-client-hunting-mvp"


def test_windows_helper_loads_local_env_when_present():
    script = (Path(__file__).resolve().parent.parent / "run.ps1").read_text()
    assert 'Test-Path ".env"' in script
    assert '@("--env-file", ".env")' in script
    assert "python -m uvicorn @markOsUvicornArgs" in script


def test_public_health_static_and_protected_home_behavior():
    health_status, _, health_body = asyncio.run(_request("/health"))
    home_status, home_headers, _ = asyncio.run(_request("/"))
    static_status, _, _ = asyncio.run(_request("/static/quests.css"))

    assert health_status == 200
    assert health_body == b'{"status":"ok","version":"0.3.0-client-hunting-mvp"}'
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

    for target in (
        "/",
        "/quests",
        "/quests/1",
        "/goals",
        "/crm",
        "/life-os",
        "/history",
    ):
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


def test_crm_create_edit_pipeline_next_action_and_delete_routes_persist(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "crm-routes.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()
    cookie, _ = _login_cookie(monkeypatch)

    missing_status, _, _ = asyncio.run(
        _request("/crm/leads/999", headers=[(b"cookie", cookie)])
    )
    assert missing_status == 404

    create_data = {
        "company": "Northstar Analytics",
        "contact_person": "Ada Reyes",
        "job_title": "Founder",
        "source": "LinkedIn",
        "source_url": "https://example.com/northstar",
        "problem_opportunity": "Reporting is slow and difficult to trust.",
        "why_mark_fits": "Data engineering and product delivery experience.",
        "pipeline_status": "new",
        "priority": "high",
        "next_action": "Send a focused introduction",
        "next_action_due_date": "2026-08-05",
        "notes": "Warm signal from a public post.",
        "request_key": "application-route-create-1",
    }
    create_status, create_headers, _ = _post_form(
        "/crm/leads",
        create_data,
        cookie=cookie,
    )
    duplicate_status, duplicate_headers, _ = _post_form(
        "/crm/leads",
        create_data,
        cookie=cookie,
    )

    assert (create_status, _header_values(create_headers, b"location")) == (
        303,
        [b"/crm/leads/1?notice=created"],
    )
    assert (duplicate_status, _header_values(duplicate_headers, b"location")) == (
        303,
        [b"/crm/leads/1?notice=duplicate"],
    )

    detail_status, _, detail_body = asyncio.run(
        _request("/crm/leads/1", headers=[(b"cookie", cookie)])
    )
    assert detail_status == 200
    assert b"Northstar Analytics" in detail_body
    assert b"QUEST #" in detail_body

    dashboard_status, _, dashboard_body = asyncio.run(
        _request("/crm", headers=[(b"cookie", cookie)])
    )
    assert dashboard_status == 200
    for metric_label in (
        b"Total leads",
        b"High-priority leads",
        b"Contacted",
        b"Replies",
        b"Meetings",
        b"Proposals",
        b"Won clients",
    ):
        assert metric_label in dashboard_body

    today_status, _, today_body = asyncio.run(
        _request("/", headers=[(b"cookie", cookie)])
    )
    assert today_status == 200
    assert b"Client: Northstar Analytics" in today_body
    assert b"CRM QUEST" in today_body

    edit_status, edit_headers, _ = _post_form(
        "/crm/leads/1/edit",
        {
            **create_data,
            "company": "Northstar Data Studio",
            "contact_person": "Ada Santos",
            "pipeline_status": "reviewed",
            "priority": "medium",
            "next_action": "Draft a one-page audit offer",
            "next_action_due_date": "2026-08-06",
            "notes": "Qualified after reviewing the company site.",
        },
        cookie=cookie,
    )
    pipeline_status, pipeline_headers, _ = _post_form(
        "/crm/leads/1/pipeline",
        {"pipeline_status": "replied"},
        cookie=cookie,
    )
    next_action_status, next_action_headers, _ = _post_form(
        "/crm/leads/1/next-action",
        {
            "next_action": "Book a discovery call",
            "next_action_due_date": "2026-08-08",
        },
        cookie=cookie,
    )

    assert (edit_status, _header_values(edit_headers, b"location")) == (
        303,
        [b"/crm/leads/1?notice=updated"],
    )
    assert (pipeline_status, _header_values(pipeline_headers, b"location")) == (
        303,
        [b"/crm/leads/1?notice=pipeline"],
    )
    assert (
        next_action_status,
        _header_values(next_action_headers, b"location"),
    ) == (303, [b"/crm/leads/1?notice=next_action"])

    rejected_status, _, rejected_body = _post_form(
        "/crm/leads/1/delete",
        {"confirmation": "delete"},
        cookie=cookie,
    )
    assert rejected_status == 400
    assert b"Type DELETE exactly" in rejected_body

    with database.get_db() as db:
        lead_before_delete = db.execute(
            """
            SELECT company, contact_person, pipeline_status, priority,
                   next_action, next_action_due_date, quest_id, deleted_at
            FROM leads WHERE id = 1
            """
        ).fetchone()
        lead_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        quest = db.execute(
            "SELECT id, title FROM tasks WHERE id = ?",
            (lead_before_delete["quest_id"],),
        ).fetchone()

    assert lead_count == 1
    assert tuple(lead_before_delete) == (
        "Northstar Data Studio",
        "Ada Santos",
        "replied",
        "medium",
        "Book a discovery call",
        "2026-08-08",
        quest["id"],
        None,
    )
    assert "Northstar" in quest["title"]

    quest_detail_status, _, quest_detail_body = asyncio.run(
        _request(f"/quests/{quest['id']}", headers=[(b"cookie", cookie)])
    )
    assert quest_detail_status == 200
    assert b"Managed from the CRM" in quest_detail_body

    guarded_completion_status, guarded_completion_headers, _ = _post_form(
        f"/quests/{quest['id']}/complete",
        {"result_notes": "Should be managed through the CRM"},
        cookie=cookie,
    )
    assert (
        guarded_completion_status,
        _header_values(guarded_completion_headers, b"location"),
    ) == (303, [b"/crm/leads/1"])

    with database.get_db() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM xp_ledger WHERE task_id = ?", (quest["id"],)
        ).fetchone()[0] == 0

    delete_status, delete_headers, _ = _post_form(
        "/crm/leads/1/delete",
        {"confirmation": "DELETE"},
        cookie=cookie,
    )
    assert (delete_status, _header_values(delete_headers, b"location")) == (
        303,
        [b"/crm?notice=deleted"],
    )

    with database.get_db() as db:
        archived_lead = db.execute(
            "SELECT deleted_at, quest_id FROM leads WHERE id = 1"
        ).fetchone()
        linked_quest = db.execute(
            "SELECT id, status FROM tasks WHERE id = ?",
            (archived_lead["quest_id"],),
        ).fetchone()

    assert archived_lead["deleted_at"] is not None
    assert linked_quest is not None
    assert linked_quest["status"] == "abandoned"

    archived_quest_status, _, archived_quest_body = asyncio.run(
        _request(f"/quests/{linked_quest['id']}", headers=[(b"cookie", cookie)])
    )
    assert archived_quest_status == 200
    assert b"Archived Client Hunting quest" in archived_quest_body

    guarded_archived_status, guarded_archived_headers, _ = _post_form(
        f"/quests/{linked_quest['id']}/start",
        {},
        cookie=cookie,
    )
    assert (
        guarded_archived_status,
        _header_values(guarded_archived_headers, b"location"),
    ) == (303, [b"/crm"])

    with database.get_db() as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE id = ?", (linked_quest["id"],)
        ).fetchone()[0] == "abandoned"
