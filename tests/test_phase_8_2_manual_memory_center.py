from __future__ import annotations

import asyncio
from urllib.parse import urlencode, urlsplit

import pytest

from app import database
from app.main import app
from app.services.access_control import can_access_request
from app.services.memory import (
    MemoryConflictError,
    archive_memory,
    create_memory,
    create_memory_candidate,
    list_memories,
    list_memory_audit_events,
    revise_memory,
)
from app.services.passwords import hash_password
from app.services.team_users import create_member


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def memory_center_database(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "phase-8-2.db")
    _configure_owner(monkeypatch)
    database.init_db()
    with database.get_db() as db:
        owner_id = int(
            db.execute("SELECT id FROM users WHERE role = 'owner'").fetchone()[0]
        )
        member = create_member(
            db,
            username="member",
            display_name="Member",
            password="member-password-123",
            password_confirmation="member-password-123",
        )
        db.execute(
            "UPDATE users SET must_change_password = 0 WHERE id = ?",
            (member["id"],),
        )
    return owner_id, int(member["id"])


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
    start = next(item for item in messages if item["type"] == "http.response.start")
    response_body = b"".join(
        item.get("body", b"")
        for item in messages
        if item["type"] == "http.response.body"
    )
    return start["status"], start["headers"], response_body


def _header_values(headers, name: bytes) -> list[bytes]:
    return [value for key, value in headers if key.lower() == name.lower()]


def _login_cookie(username: str, password: str) -> bytes:
    body = urlencode({"username": username, "password": password}).encode()
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
    return _header_values(headers, b"set-cookie")[0].split(b";", 1)[0]


def _post(path: str, data: dict[str, str], cookie: bytes):
    body = urlencode(data).encode()
    return asyncio.run(
        _request(
            path,
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", str(len(body)).encode()),
            ],
            body=body,
        )
    )


def _memory_fields(**overrides) -> dict[str, str]:
    values = {
        "memory_type": "preference",
        "memory_key": "focus_window",
        "memory_value": "I protect mornings for focused analytical work.",
        "importance": "8",
        "source": "manual journal",
        "confidence": "0.95",
        "sensitivity": "private",
    }
    values.update(overrides)
    return values


def test_manual_memory_revisions_preserve_history_and_content_free_audit(
    memory_center_database,
):
    owner_id, member_id = memory_center_database
    with database.get_db() as db:
        first = create_memory(db, user_id=owner_id, **_memory_fields())
        second = revise_memory(
            db,
            int(first["id"]),
            expected_version=1,
            memory_type="preference",
            memory_value="I protect 8–11 AM for focused analytical work.",
            importance=9,
            source="manual review",
            confidence=1.0,
            sensitivity="private",
            user_id=owner_id,
        )

        old = db.execute(
            "SELECT * FROM memories WHERE id = ?",
            (first["id"],),
        ).fetchone()
        assert second["version"] == 2
        assert second["active"] == 1
        assert old["active"] == 0
        assert old["superseded_by"] == second["id"]
        focus_rows = [
            row
            for row in list_memories(db, user_id=owner_id)
            if row["memory_key"] == "focus_window"
        ]
        assert [row["id"] for row in focus_rows] == [second["id"]]
        assert list_memories(db, user_id=member_id) == []

        audit = list_memory_audit_events(db, user_id=owner_id)
        assert [row["event_type"] for row in audit] == [
            "memory_created",
            "memory_superseded",
            "memory_created",
        ]
        assert all("focused analytical" not in row["details_json"] for row in audit)


def test_stale_mutations_fail_without_changing_other_life_os_state(
    memory_center_database,
):
    owner_id, _ = memory_center_database
    with database.get_db() as db:
        before = {
            "tasks": [tuple(row) for row in db.execute("SELECT * FROM tasks")],
            "xp": [tuple(row) for row in db.execute("SELECT * FROM xp_ledger")],
            "game": [tuple(row) for row in db.execute("SELECT * FROM game_state")],
        }
        first = create_memory(db, user_id=owner_id, **_memory_fields())
        current = revise_memory(
            db,
            int(first["id"]),
            expected_version=1,
            memory_type="preference",
            memory_value="Current value",
            importance=8,
            source="manual",
            confidence=1.0,
            sensitivity="normal",
            user_id=owner_id,
        )
        with pytest.raises(MemoryConflictError, match="changed"):
            revise_memory(
                db,
                int(first["id"]),
                expected_version=1,
                memory_type="preference",
                memory_value="Stale overwrite",
                importance=8,
                source="manual",
                confidence=1.0,
                sensitivity="normal",
                user_id=owner_id,
            )
        with pytest.raises(MemoryConflictError, match="changed"):
            archive_memory(
                db,
                int(first["id"]),
                expected_version=1,
                user_id=owner_id,
            )
        assert current["active"] == 1
        assert [tuple(row) for row in db.execute("SELECT * FROM tasks")] == before[
            "tasks"
        ]
        assert [tuple(row) for row in db.execute("SELECT * FROM xp_ledger")] == before[
            "xp"
        ]
        assert [tuple(row) for row in db.execute("SELECT * FROM game_state")] == before[
            "game"
        ]


def test_manual_memory_rejects_secrets_without_writes(memory_center_database):
    owner_id, _ = memory_center_database
    with database.get_db() as db:
        memory_count = db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        audit_count = db.execute(
            "SELECT COUNT(*) FROM memory_audit_events"
        ).fetchone()[0]
        with pytest.raises(ValueError, match="cannot be stored"):
            create_memory(
                db,
                user_id=owner_id,
                **_memory_fields(memory_value="password=hunter2"),
            )
        assert db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == memory_count
        assert (
            db.execute("SELECT COUNT(*) FROM memory_audit_events").fetchone()[0]
            == audit_count
        )


def test_memory_center_routes_render_validate_and_archive(memory_center_database):
    owner_id, _ = memory_center_database
    with database.get_db() as db:
        db.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (hash_password("owner-route-password"), owner_id),
        )
        username = db.execute(
            "SELECT username FROM users WHERE id = ?", (owner_id,)
        ).fetchone()[0]
        candidate = create_memory_candidate(
            db,
            user_id=owner_id,
            memory_type="lesson",
            memory_key="review_weekly",
            memory_value="Review the operating system once a week.",
            source="test suggestion",
            candidate_reason="Repeated planning practice.",
        ).candidate
    cookie = _login_cookie(username, "owner-route-password")

    status, _, body = asyncio.run(
        _request("/memories", headers=[(b"cookie", cookie)])
    )
    assert status == 200
    assert b"Manual Memory Center" in body
    assert b"Pending candidates" in body
    assert b"Review the operating system once a week." in body
    assert b'<div class="notification' not in body

    status, _, body = _post(
        "/memories",
        _memory_fields(memory_value="", memory_key="preserved_key"),
        cookie,
    )
    assert status == 422
    assert b"Memory value is required" in body
    assert b'value="preserved_key"' in body

    status, _, body = _post(
        "/memories",
        _memory_fields(memory_value="password=hunter2"),
        cookie,
    )
    assert status == 422
    assert b"Secrets and banking information cannot be stored" in body
    assert b"hunter2" not in body

    status, headers, _ = _post("/memories", _memory_fields(), cookie)
    assert status == 303
    assert _header_values(headers, b"location") == [b"/memories?notice=created"]
    with database.get_db() as db:
        memory = db.execute(
            "SELECT * FROM memories WHERE user_id = ? AND memory_key = ?",
            (owner_id, "focus_window"),
        ).fetchone()

    status, _, body = asyncio.run(
        _request(
            f"/memories/{memory['id']}/edit",
            headers=[(b"cookie", cookie)],
        )
    )
    assert status == 200
    assert b"Saving creates version 2" in body
    assert b'name="expected_version" value="1"' in body

    revised_fields = _memory_fields(
        expected_version="1",
        memory_value="I now protect 8–11 AM for focused analytical work.",
    )
    status, headers, _ = _post(
        f"/memories/{memory['id']}/edit",
        revised_fields,
        cookie,
    )
    assert status == 303
    assert _header_values(headers, b"location") == [b"/memories?notice=updated"]
    with database.get_db() as db:
        current = db.execute(
            """
            SELECT * FROM memories
            WHERE user_id = ? AND memory_key = 'focus_window' AND active = 1
            """,
            (owner_id,),
        ).fetchone()
    assert current["version"] == 2

    status, headers, _ = _post(
        f"/memories/{memory['id']}/edit",
        revised_fields,
        cookie,
    )
    assert status == 303
    assert _header_values(headers, b"location") == [b"/memories?error=stale"]

    status, headers, _ = _post(
        f"/memories/{current['id']}/archive",
        {"expected_version": "2"},
        cookie,
    )
    assert status == 303
    assert _header_values(headers, b"location") == [b"/memories?notice=archived"]

    status, headers, _ = _post(
        f"/memories/candidates/{candidate['id']}/accept",
        {},
        cookie,
    )
    assert status == 303
    assert _header_values(headers, b"location") == [b"/memories?notice=accepted"]
    with database.get_db() as db:
        assert db.execute(
            "SELECT active FROM memories WHERE id = ?", (current["id"],)
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT status FROM memory_candidates WHERE id = ?", (candidate["id"],)
        ).fetchone()[0] == "accepted"
        assert db.execute(
            """
            SELECT COUNT(*) FROM memories
            WHERE user_id = ? AND memory_key = 'review_weekly' AND active = 1
            """,
            (owner_id,),
        ).fetchone()[0] == 1


def test_cross_user_candidate_route_is_not_found(memory_center_database):
    owner_id, member_id = memory_center_database
    with database.get_db() as db:
        memory = create_memory(db, user_id=owner_id, **_memory_fields())
        candidate = create_memory_candidate(
            db,
            user_id=owner_id,
            memory_type="profile",
            memory_key="owner_only",
            memory_value="Owner-only memory candidate.",
            source="test",
            candidate_reason="Isolation test.",
        ).candidate
    cookie = _login_cookie("member", "member-password-123")
    status, _, _ = asyncio.run(
        _request(
            f"/memories/{memory['id']}/edit",
            headers=[(b"cookie", cookie)],
        )
    )
    assert status == 404
    status, _, _ = _post(
        f"/memories/{memory['id']}/archive",
        {"expected_version": "1"},
        cookie,
    )
    assert status == 404
    status, _, _ = _post(
        f"/memories/candidates/{candidate['id']}/accept",
        {},
        cookie,
    )
    assert status == 404
    with database.get_db() as db:
        assert db.execute(
            "SELECT status FROM memory_candidates WHERE id = ?", (candidate["id"],)
        ).fetchone()[0] == "pending"
        assert db.execute(
            "SELECT active FROM memories WHERE id = ?", (memory["id"],)
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM memories WHERE user_id = ?", (member_id,)
        ).fetchone()[0] == 0


def test_memory_center_permissions_are_personal_only():
    member = {"id": 2, "role": "member"}
    sourcer = {"id": 3, "role": "lead_sourcer"}
    allowed = (
        ("GET", "/memories"),
        ("POST", "/memories"),
        ("GET", "/memories/1/edit"),
        ("POST", "/memories/1/edit"),
        ("POST", "/memories/1/archive"),
        ("POST", "/memories/candidates/1/accept"),
        ("POST", "/memories/candidates/1/reject"),
        ("POST", "/memories/candidates/1/archive"),
    )
    assert all(can_access_request(member, method, path) for method, path in allowed)
    assert not any(can_access_request(sourcer, method, path) for method, path in allowed)
