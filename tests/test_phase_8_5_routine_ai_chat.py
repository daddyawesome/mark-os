from __future__ import annotations

import asyncio
import json
import urllib.error
from urllib.parse import urlencode, urlsplit

import pytest

from app import database
from app.main import app
from app.services import provider_gateway
from app.services.access_control import can_access_request
from app.services.agent_audit import list_agent_steps
from app.services.chat import create_chat_session, get_recent_chat_messages
from app.services.chat_orchestrator import (
    BUDGET_REPLY,
    DISABLED_REPLY,
    FAILURE_REPLY,
    send_chat_message,
)
from app.services.memory import create_memory, list_memories
from app.services.team_users import create_member


REQUIRED_ENV = {
    "OPENAI_API_KEY": "sk-test-key",
    "OPENAI_MODEL": "gpt-test-model",
    "OPENAI_INPUT_PRICE_MICROUSD_PER_1K": "100",
    "OPENAI_OUTPUT_PRICE_MICROUSD_PER_1K": "200",
    "MARK_OS_AI_MONTHLY_BUDGET_MICROUSD": "3500000",
}


def _set_required_env(monkeypatch, overrides: dict | None = None) -> None:
    values = dict(REQUIRED_ENV)
    values.update(overrides or {})
    for name, value in values.items():
        monkeypatch.setenv(name, value)


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _success_urlopen(reply_text="Focus on the highest-leverage task today.", calls=None):
    def fake_urlopen(request, timeout=None):
        if calls is not None:
            calls.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse(
            {
                "choices": [{"message": {"content": reply_text}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            }
        )

    return fake_urlopen


@pytest.fixture
def chat_database(tmp_path, monkeypatch):
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "phase-8-5.db")
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


def _snapshot(db, table: str) -> list[tuple]:
    return [tuple(row) for row in db.execute(f"SELECT * FROM {table}")]


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


def test_routine_chat_success_persists_both_messages_and_completes_audit(
    chat_database, monkeypatch
):
    owner_id, _member_id = chat_database
    _set_required_env(monkeypatch)
    monkeypatch.setattr(
        provider_gateway.urllib.request, "urlopen", _success_urlopen()
    )

    with database.get_db() as db:
        session = create_chat_session(db, user_id=owner_id)
        result = send_chat_message(
            db,
            session_id=session["id"],
            content="How should I plan my week?",
            request_key="req-1",
            user_id=owner_id,
        )

        assert result.user_message["content"] == "How should I plan my week?"
        assert result.assistant_message["content"] == (
            "Focus on the highest-leverage task today."
        )
        assert result.loop_selected == "routine_chat"
        assert result.run["status"] == "completed"
        assert result.run["intent"] == "general_chat"

        steps = list_agent_steps(db, result.run["id"])
        assert len(steps) == 1
        assert steps[0]["status"] == "completed"
        assert steps[0]["input_tokens"] == 120
        assert steps[0]["output_tokens"] == 30

        messages = get_recent_chat_messages(db, session["id"], user_id=owner_id)
        assert [m["role"] for m in messages] == ["user", "assistant"]


def test_deterministic_my_level_never_touches_provider(chat_database, monkeypatch):
    owner_id, _member_id = chat_database
    # No OPENAI_* env configured at all, and urlopen would raise if reached.
    def fail_if_called(request, timeout=None):
        raise AssertionError("Deterministic path must not call the provider")

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", fail_if_called)

    with database.get_db() as db:
        db.execute(
            """
            UPDATE game_state
            SET level = 5, xp_total = 420, character_class = 'Business Owner'
            WHERE user_id = ?
            """,
            (owner_id,),
        )
        session = create_chat_session(db, user_id=owner_id)
        result = send_chat_message(
            db,
            session_id=session["id"],
            content="what is my level right now",
            user_id=owner_id,
        )

    assert "level 5" in result.assistant_message["content"]
    assert result.loop_selected == "data_lookup"
    assert result.run["status"] == "completed"


def test_deterministic_show_memories(chat_database):
    owner_id, _member_id = chat_database
    with database.get_db() as db:
        create_memory(
            db,
            memory_type="preference",
            memory_key="deep_work_window",
            memory_value="Mornings are reserved for deep work.",
            sensitivity="normal",
            user_id=owner_id,
        )
        session = create_chat_session(db, user_id=owner_id)
        result = send_chat_message(
            db,
            session_id=session["id"],
            content="please show my memories",
            user_id=owner_id,
        )

    assert "deep_work_window" in result.assistant_message["content"]
    assert result.loop_selected == "memory_management"


def test_memory_write_intent_declines_without_writing(chat_database):
    owner_id, _member_id = chat_database
    with database.get_db() as db:
        before = _snapshot(db, "memories")
        session = create_chat_session(db, user_id=owner_id)
        result = send_chat_message(
            db,
            session_id=session["id"],
            content="remember that I prefer async standups",
            user_id=owner_id,
        )
        after = _snapshot(db, "memories")

    assert "can't save or delete memories" in result.assistant_message["content"]
    assert before == after


def test_user_isolation_route_returns_not_found_for_other_users_session(
    chat_database, monkeypatch
):
    owner_id, member_id = chat_database
    with database.get_db() as db:
        owner_session = create_chat_session(db, user_id=owner_id)

    # Log in as the member and try to read/post to the owner's session id.
    member_cookie = _login_cookie(monkeypatch, "member", "member-password-123")

    status, _headers, _body = asyncio.run(
        _get(f"/chat/{owner_session['id']}", member_cookie)
    )
    assert status == 404

    status, _headers, _body = asyncio.run(
        _post(
            f"/chat/{owner_session['id']}/messages",
            {"content": "peeking", "request_key": "peek-1"},
            member_cookie,
        )
    )
    assert status == 404


def test_relationship_manager_and_lead_sourcer_cannot_reach_chat():
    relationship_manager = {"role": "relationship_manager"}
    lead_sourcer = {"role": "lead_sourcer"}

    assert can_access_request(relationship_manager, "GET", "/chat") is False
    assert can_access_request(relationship_manager, "POST", "/chat/new") is False
    assert can_access_request(relationship_manager, "GET", "/chat/1") is False
    assert can_access_request(relationship_manager, "POST", "/chat/1/messages") is False

    assert can_access_request(lead_sourcer, "GET", "/chat") is False
    assert can_access_request(lead_sourcer, "POST", "/chat/new") is False
    assert can_access_request(lead_sourcer, "GET", "/chat/1") is False
    assert can_access_request(lead_sourcer, "POST", "/chat/1/messages") is False


def test_owner_and_member_can_reach_chat():
    assert can_access_request({"role": "owner"}, "GET", "/chat") is True
    assert can_access_request({"role": "member"}, "GET", "/chat") is True
    assert can_access_request({"role": "member"}, "POST", "/chat/new") is True
    assert can_access_request({"role": "member"}, "GET", "/chat/1") is True
    assert can_access_request({"role": "member"}, "POST", "/chat/1/messages") is True


def test_disabled_provider_degrades_safely(chat_database, monkeypatch):
    owner_id, _member_id = chat_database
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with database.get_db() as db:
        session = create_chat_session(db, user_id=owner_id)
        result = send_chat_message(
            db,
            session_id=session["id"],
            content="Tell me something interesting about the moon.",
            user_id=owner_id,
        )

    assert result.assistant_message["content"] == DISABLED_REPLY
    assert result.run["status"] == "completed"
    steps = None
    with database.get_db() as db:
        steps = list_agent_steps(db, result.run["id"])
    assert steps[0]["status"] == "skipped"


def test_budget_exhausted_degrades_safely(chat_database, monkeypatch):
    owner_id, _member_id = chat_database
    _set_required_env(monkeypatch, {"MARK_OS_AI_MONTHLY_BUDGET_MICROUSD": "1"})

    def fail_if_called(request, timeout=None):
        raise AssertionError("Budget-exhausted path must not call the provider")

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", fail_if_called)

    with database.get_db() as db:
        session = create_chat_session(db, user_id=owner_id)
        result = send_chat_message(
            db,
            session_id=session["id"],
            content="Tell me something interesting about the moon.",
            user_id=owner_id,
        )

    assert result.assistant_message["content"] == BUDGET_REPLY
    assert result.run["status"] == "completed"


def test_provider_failure_does_not_corrupt_chat_state(chat_database, monkeypatch):
    owner_id, _member_id = chat_database
    _set_required_env(monkeypatch)

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection reset")

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", fake_urlopen)

    with database.get_db() as db:
        session = create_chat_session(db, user_id=owner_id)
        result = send_chat_message(
            db,
            session_id=session["id"],
            content="Tell me something interesting about the moon.",
            user_id=owner_id,
        )

        assert result.assistant_message["content"] == FAILURE_REPLY
        assert result.run["status"] == "completed"

        messages = get_recent_chat_messages(db, session["id"], user_id=owner_id)
        assert [m["role"] for m in messages] == ["user", "assistant"]

        steps = list_agent_steps(db, result.run["id"])
        assert steps[0]["status"] == "failed"
        assert steps[0]["error_message"]


def test_retry_with_same_request_key_does_not_double_call_provider(
    chat_database, monkeypatch
):
    owner_id, _member_id = chat_database
    _set_required_env(monkeypatch)
    calls: list[dict] = []
    monkeypatch.setattr(
        provider_gateway.urllib.request, "urlopen", _success_urlopen(calls=calls)
    )

    with database.get_db() as db:
        session = create_chat_session(db, user_id=owner_id)
        first = send_chat_message(
            db,
            session_id=session["id"],
            content="What should I focus on?",
            request_key="retry-key-1",
            user_id=owner_id,
        )
        second = send_chat_message(
            db,
            session_id=session["id"],
            content="What should I focus on?",
            request_key="retry-key-1",
            user_id=owner_id,
        )

        messages = get_recent_chat_messages(db, session["id"], user_id=owner_id)

    assert len(calls) == 1
    assert second.already_processed is True
    assert second.assistant_message["id"] == first.assistant_message["id"]
    assert len(messages) == 2


def test_context_scoping_excludes_other_users_data(chat_database, monkeypatch):
    owner_id, member_id = chat_database
    _set_required_env(monkeypatch)
    calls: list[dict] = []
    monkeypatch.setattr(
        provider_gateway.urllib.request, "urlopen", _success_urlopen(calls=calls)
    )

    with database.get_db() as db:
        create_memory(
            db,
            memory_type="secret",
            memory_key="member_only_fact",
            memory_value="Member's private planning notes that must never leak.",
            sensitivity="normal",
            user_id=member_id,
        )
        create_memory(
            db,
            memory_type="preference",
            memory_key="owner_fact",
            memory_value="Owner likes async standups.",
            sensitivity="normal",
            user_id=owner_id,
        )
        session = create_chat_session(db, user_id=owner_id)
        send_chat_message(
            db,
            session_id=session["id"],
            content="What do you know about my preferences?",
            user_id=owner_id,
        )

    sent_payload = json.dumps(calls[0])
    assert "member_only_fact" not in sent_payload
    assert "Member's private planning notes" not in sent_payload


def test_no_memory_candidate_or_memory_extraction_happens(chat_database, monkeypatch):
    owner_id, _member_id = chat_database
    _set_required_env(monkeypatch)
    monkeypatch.setattr(
        provider_gateway.urllib.request, "urlopen", _success_urlopen()
    )

    with database.get_db() as db:
        before_memories = _snapshot(db, "memories")
        before_candidates = _snapshot(db, "memory_candidates")
        session = create_chat_session(db, user_id=owner_id)
        send_chat_message(
            db,
            session_id=session["id"],
            content="Remember that I hate long meetings, and plan my day.",
            user_id=owner_id,
        )
        after_memories = _snapshot(db, "memories")
        after_candidates = _snapshot(db, "memory_candidates")

    assert before_memories == after_memories
    assert before_candidates == after_candidates


def test_no_xp_or_game_state_writes_from_chat(chat_database, monkeypatch):
    owner_id, _member_id = chat_database
    _set_required_env(monkeypatch)
    monkeypatch.setattr(
        provider_gateway.urllib.request, "urlopen", _success_urlopen()
    )

    with database.get_db() as db:
        before_game_state = _snapshot(db, "game_state")
        before_xp = _snapshot(db, "xp_ledger")
        session = create_chat_session(db, user_id=owner_id)
        send_chat_message(
            db,
            session_id=session["id"],
            content="Congratulate me and give me XP for finishing my quest.",
            user_id=owner_id,
        )
        after_game_state = _snapshot(db, "game_state")
        after_xp = _snapshot(db, "xp_ledger")

    assert before_game_state == after_game_state
    assert before_xp == after_xp


def test_no_tool_side_effects_from_chat(chat_database, monkeypatch):
    owner_id, _member_id = chat_database
    _set_required_env(monkeypatch)
    monkeypatch.setattr(
        provider_gateway.urllib.request, "urlopen", _success_urlopen()
    )

    with database.get_db() as db:
        before_quests = _snapshot(db, "tasks")
        session = create_chat_session(db, user_id=owner_id)
        send_chat_message(
            db,
            session_id=session["id"],
            content="Send an email to my client about the proposal.",
            user_id=owner_id,
        )
        after_quests = _snapshot(db, "tasks")

    assert before_quests == after_quests


# ---------------------------------------------------------------------------
# HTTP-level wiring tests
# ---------------------------------------------------------------------------


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


def _login_cookie(monkeypatch, username: str, password: str) -> bytes:
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


async def _get(path: str, cookie: bytes):
    return await _request(path, headers=[(b"cookie", cookie)])


async def _post(path: str, data: dict[str, str], cookie: bytes):
    body = urlencode(data).encode()
    return await _request(
        path,
        method="POST",
        headers=[
            (b"cookie", cookie),
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"content-length", str(len(body)).encode()),
        ],
        body=body,
    )


def test_http_flow_start_chat_and_send_message(chat_database, monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setattr(
        provider_gateway.urllib.request, "urlopen", _success_urlopen()
    )

    cookie = _login_cookie(monkeypatch, "mark", "owner-password-123")

    status, headers, _body = asyncio.run(_post("/chat/new", {}, cookie))
    assert status == 303
    location = _header_values(headers, b"location")[0].decode()
    assert location.startswith("/chat/")

    status, _headers, body = asyncio.run(_get(location, cookie))
    assert status == 200
    assert b"Chat" in body

    session_id = location.rsplit("/", 1)[-1]
    status, _headers, body = asyncio.run(
        _post(
            f"/chat/{session_id}/messages",
            {"content": "How should I plan my day?", "request_key": "http-1"},
            cookie,
        )
    )
    assert status == 303

    status, _headers, body = asyncio.run(_get(f"/chat/{session_id}", cookie))
    assert status == 200
    assert b"How should I plan my day?" in body
    assert b"Focus on the highest-leverage task today." in body
