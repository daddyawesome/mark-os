from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

from app import database
from app.db.organizations import organization_id_by_slug
from app.main import app
from app.services.webhook_intake import create_webhook_token


OWNER = {"id": 1, "role": "owner"}


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

    start = next(m for m in messages if m["type"] == "http.response.start")
    response_body = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    return start["status"], start["headers"], response_body


def _setup_token(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "webhook-route.db")
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")
    database.init_db()
    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        issued = create_webhook_token(
            db,
            actor=OWNER,
            organization_id=organization_id,
            source_name="Route test source",
        )
    return issued.token


def test_intake_route_creates_a_lead_with_valid_token(tmp_path, monkeypatch):
    token = _setup_token(tmp_path, monkeypatch)
    payload = json.dumps(
        {
            "external_id": "route-ext-1",
            "company": "Blue Harbor Studio",
            "contact_person": "Leo Cruz",
            "message": "Manual spreadsheets delay weekly decisions.",
        }
    ).encode()

    status, headers, body = asyncio.run(
        _request(
            "/api/leads/intake",
            method="POST",
            headers=[
                (b"authorization", f"Bearer {token}".encode()),
                (b"content-type", b"application/json"),
            ],
            body=payload,
        )
    )

    assert status == 201
    result = json.loads(body)
    assert result["outcome"] == "created"
    assert result["lead_id"] is not None


def test_intake_route_rejects_missing_authorization_header(
    tmp_path,
    monkeypatch,
):
    _setup_token(tmp_path, monkeypatch)
    status, _, body = asyncio.run(
        _request(
            "/api/leads/intake",
            method="POST",
            headers=[(b"content-type", b"application/json")],
            body=json.dumps({"external_id": "x"}).encode(),
        )
    )
    assert status == 401


def test_intake_route_rejects_invalid_token(tmp_path, monkeypatch):
    _setup_token(tmp_path, monkeypatch)
    status, _, _ = asyncio.run(
        _request(
            "/api/leads/intake",
            method="POST",
            headers=[
                (b"authorization", b"Bearer completely-wrong-token"),
                (b"content-type", b"application/json"),
            ],
            body=json.dumps(
                {
                    "external_id": "x",
                    "company": "A",
                    "contact_person": "B",
                    "message": "C",
                }
            ).encode(),
        )
    )
    assert status == 401


def test_intake_route_rejects_malformed_json(tmp_path, monkeypatch):
    token = _setup_token(tmp_path, monkeypatch)
    status, _, _ = asyncio.run(
        _request(
            "/api/leads/intake",
            method="POST",
            headers=[
                (b"authorization", f"Bearer {token}".encode()),
                (b"content-type", b"application/json"),
            ],
            body=b"{not valid json",
        )
    )
    assert status == 400


def test_intake_route_rejects_incomplete_payload_without_writing(
    tmp_path,
    monkeypatch,
):
    token = _setup_token(tmp_path, monkeypatch)
    status, _, body = asyncio.run(
        _request(
            "/api/leads/intake",
            method="POST",
            headers=[
                (b"authorization", f"Bearer {token}".encode()),
                (b"content-type", b"application/json"),
            ],
            body=json.dumps({"external_id": "incomplete"}).encode(),
        )
    )
    assert status == 422

    with database.get_db() as db:
        lead_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    assert lead_count == 0


def test_intake_route_does_not_require_a_session_cookie(tmp_path, monkeypatch):
    # The route is reachable without ever logging in — that's the point of
    # a bearer-token-authenticated machine-to-machine endpoint. Confirmed by
    # every test above never sending a cookie header.
    token = _setup_token(tmp_path, monkeypatch)
    status, _, _ = asyncio.run(
        _request(
            "/api/leads/intake",
            method="POST",
            headers=[(b"authorization", f"Bearer {token}".encode())],
            body=b"{}",
        )
    )
    assert status == 422
