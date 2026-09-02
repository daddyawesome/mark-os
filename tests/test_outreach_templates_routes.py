from __future__ import annotations

import asyncio
from urllib.parse import urlencode, urlsplit

from app import database
from app.main import app
from app.services.leads import create_lead
from app.services.outreach_templates import list_templates, set_template_approval
from app.services.passwords import hash_password


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


def _header_values(headers, name: bytes) -> list[bytes]:
    return [value for key, value in headers if key.lower() == name.lower()]


def _login_cookie(monkeypatch) -> bytes:
    database.init_db()
    with database.get_db() as db:
        db.execute("DELETE FROM users WHERE username = ?", ("owner-test-user",))
        db.execute(
            """
            INSERT INTO users (
                username, display_name, password_hash,
                role, active, must_change_password
            )
            VALUES (?, ?, ?, 'owner', 1, 0)
            """,
            (
                "owner-test-user",
                "Owner Test",
                hash_password("owner-test-password"),
            ),
        )
    body = urlencode(
        {"username": "owner-test-user", "password": "owner-test-password"}
    ).encode()
    _, headers, _ = asyncio.run(
        _request(
            "/login",
            method="POST",
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            body=body,
        )
    )
    set_cookie = _header_values(headers, b"set-cookie")[0]
    return set_cookie.split(b";", 1)[0]


def test_lead_aware_template_use_prefills_and_links_back_to_the_lead(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "template-lead-flow.db")
    cookie = _login_cookie(monkeypatch)

    with database.get_db() as db:
        organization_id = db.execute(
            "SELECT id FROM organizations WHERE slug='mark-agency'"
        ).fetchone()[0]
        owner_id = db.execute(
            "SELECT id FROM users WHERE username='owner-test-user'"
        ).fetchone()[0]
        lead = create_lead(
            db,
            organization_id=organization_id,
            created_by_user_id=owner_id,
            assigned_to_user_id=owner_id,
            company="Northstar Analytics",
            contact_person="Ada Reyes",
            job_title="Founder",
            source="LinkedIn",
            source_url="https://example.com/northstar",
            problem_opportunity="Reporting is slow.",
            why_mark_fits="Automation fit.",
            pipeline_status="new",
            priority="high",
            next_action="Send an intro message",
            next_action_due_date="2026-08-05",
            notes="",
        ).lead

        template = list_templates(db, organization_id=organization_id)[0]
        set_template_approval(
            db,
            template["id"],
            actor={"id": owner_id, "role": "owner"},
            organization_id=organization_id,
            approved=True,
            expected_row_version=template["row_version"],
        )

    status, _, body = asyncio.run(
        _request(
            f"/crm/templates/{template['id']}/use?lead_id={lead['id']}",
            headers=[(b"cookie", cookie)],
        )
    )
    assert status == 200
    assert b"Northstar Analytics" in body

    form_body = urlencode(
        {
            "lead_id": str(lead["id"]),
            "var_contact_person": "Ada Reyes",
            "var_opening_note": "loved your recent research",
            "var_topic": "reporting automation",
        }
    ).encode()
    status, _, body = asyncio.run(
        _request(
            f"/crm/templates/{template['id']}/use",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=form_body,
        )
    )
    assert status == 200
    assert b"Ada Reyes" in body
    assert f"/crm/leads/{lead['id']}?message_summary=".encode() in body


def test_tampered_lead_id_does_not_crash_the_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "template-tampered-lead.db")
    cookie = _login_cookie(monkeypatch)

    with database.get_db() as db:
        organization_id = db.execute(
            "SELECT id FROM organizations WHERE slug='mark-agency'"
        ).fetchone()[0]
        owner_id = db.execute(
            "SELECT id FROM users WHERE username='owner-test-user'"
        ).fetchone()[0]
        template = list_templates(db, organization_id=organization_id)[0]
        set_template_approval(
            db,
            template["id"],
            actor={"id": owner_id, "role": "owner"},
            organization_id=organization_id,
            approved=True,
            expected_row_version=template["row_version"],
        )

    form_body = urlencode({"lead_id": "not-a-number"}).encode()
    status, _, _ = asyncio.run(
        _request(
            f"/crm/templates/{template['id']}/use",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=form_body,
        )
    )
    assert status == 200
