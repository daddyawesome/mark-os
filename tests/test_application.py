from __future__ import annotations

import asyncio
import json
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi.routing import APIRoute
from starlette.routing import Mount

import app.auth as auth
from app import database
from app.main import app
from app.services.passwords import hash_password


EXPECTED_ROUTES = [
    ("GET", "/login", "login_page"),
    ("POST", "/login", "login_submit"),
    ("POST", "/logout", "logout"),
    ("GET", "/account/password", "account_password_page"),
    ("POST", "/account/password", "account_password_submit"),
    ("POST", "/workspace/select", "select_workspace"),
    ("GET", "/pendang", "pendang_home"),
    ("POST", "/pendang/profile", "update_pendang_profile"),
    ("POST", "/pendang/items", "create_pendang_item"),
    ("POST", "/pendang/items/{item_id}/edit", "edit_pendang_item"),
    ("POST", "/pendang/items/{item_id}/archive", "archive_pendang_item"),
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
    ("GET", "/relationship-manager", "relationship_manager_home"),
    ("GET", "/crm", "crm_dashboard"),
    ("GET", "/crm/follow-ups", "follow_up_command_center_page"),
    ("GET", "/crm/leads/new", "new_lead_page"),
    ("GET", "/crm/leads/export", "export_leads"),
    ("GET", "/crm/backup/download", "download_crm_backup"),
    ("POST", "/api/leads/intake", "intake_lead_webhook"),
    ("GET", "/crm/effort", "lead_sourcing_effort_page"),
    ("GET", "/crm/webhooks", "list_webhook_tokens_page"),
    ("POST", "/crm/webhooks", "create_webhook_token_route"),
    ("POST", "/crm/webhooks/{token_id}/revoke", "revoke_webhook_token_route"),
    ("GET", "/crm/leads/import/template", "download_lead_csv_template"),
    ("POST", "/crm/leads/import/preview", "preview_leads_csv"),
    ("POST", "/crm/leads/import", "import_leads_csv"),
    ("POST", "/crm/leads", "create_lead"),
    ("GET", "/crm/leads/{lead_id}", "lead_detail"),
    ("POST", "/crm/leads/{lead_id}/activities", "create_lead_activity"),
    ("POST", "/crm/leads/{lead_id}/activities/{activity_id}/correct", "correct_lead_activity"),
    ("POST", "/crm/leads/{lead_id}/activities/{activity_id}/delete", "delete_lead_activity"),
    ("GET", "/crm/leads/{lead_id}/research/edit", "edit_lead_research_page"),
    ("POST", "/crm/leads/{lead_id}/research/edit", "edit_lead_research"),
    ("POST", "/crm/leads/{lead_id}/research/submit", "submit_lead_research_for_review"),
    ("GET", "/crm/leads/{lead_id}/qualification/edit", "edit_lead_qualification_page"),
    ("POST", "/crm/leads/{lead_id}/qualification/edit", "edit_lead_qualification"),
    ("POST", "/crm/leads/{lead_id}/qualification/decide", "decide_lead_qualification"),
    ("GET", "/crm/leads/{lead_id}/proposals", "list_lead_proposals_page"),
    ("POST", "/crm/leads/{lead_id}/proposals", "create_lead_proposal"),
    ("GET", "/crm/leads/{lead_id}/proposals/{proposal_id}", "lead_proposal_detail_page"),
    ("POST", "/crm/leads/{lead_id}/proposals/{proposal_id}/edit", "edit_lead_proposal"),
    ("POST", "/crm/leads/{lead_id}/proposals/{proposal_id}/submit-review", "submit_lead_proposal_for_review"),
    ("POST", "/crm/leads/{lead_id}/proposals/{proposal_id}/approve", "approve_lead_proposal"),
    ("POST", "/crm/leads/{lead_id}/proposals/{proposal_id}/send", "send_lead_proposal"),
    ("POST", "/crm/leads/{lead_id}/proposals/{proposal_id}/decision", "decide_lead_proposal"),
    ("POST", "/crm/leads/{lead_id}/onboard", "onboard_lead_as_client"),
    ("GET", "/crm/clients", "list_clients_page"),
    ("GET", "/crm/clients/{client_id}", "client_detail_page"),
    ("POST", "/crm/clients/{client_id}/engagements", "create_client_engagement"),
    ("GET", "/crm/engagements/{engagement_id}", "engagement_detail_page"),
    ("POST", "/crm/engagements/{engagement_id}/edit", "edit_engagement"),
    ("POST", "/crm/engagements/{engagement_id}/notes", "edit_engagement_notes"),
    ("POST", "/crm/engagements/{engagement_id}/complete", "complete_engagement_route"),
    ("POST", "/crm/engagements/{engagement_id}/cancel", "cancel_engagement_route"),
    ("POST", "/crm/engagements/{engagement_id}/items", "create_engagement_item_route"),
    ("POST", "/crm/engagements/{engagement_id}/items/{item_id}/status", "update_engagement_item_status_route"),
    ("GET", "/crm/engagements/{engagement_id}/billing", "engagement_billing_page"),
    ("POST", "/crm/engagements/{engagement_id}/billing/arrangements", "create_arrangement_route"),
    ("POST", "/crm/engagements/{engagement_id}/billing/arrangements/{arrangement_id}/cancel", "cancel_arrangement_route"),
    ("POST", "/crm/engagements/{engagement_id}/billing/invoices", "create_invoice_route"),
    ("POST", "/crm/engagements/{engagement_id}/billing/invoices/{invoice_id}/status", "update_invoice_status_route"),
    ("POST", "/crm/engagements/{engagement_id}/billing/invoices/{invoice_id}/payments", "record_payment_route"),
    ("POST", "/crm/engagements/{engagement_id}/billing/payments/{payment_id}/void", "void_payment_route"),
    ("POST", "/crm/engagements/{engagement_id}/billing/costs", "create_cost_route"),
    ("POST", "/crm/engagements/{engagement_id}/billing/costs/{cost_id}/delete", "delete_cost_route"),
    ("POST", "/crm/leads/research/bulk-submit", "bulk_submit_lead_research"),
    ("POST", "/crm/leads/{lead_id}/research/review", "review_lead_research"),
    ("POST", "/crm/leads/{lead_id}/outreach/approve", "approve_lead_outreach"),
    ("GET", "/crm/research-review", "research_review_queue"),
    ("GET", "/crm/leads/{lead_id}/edit", "edit_lead_page"),
    ("POST", "/crm/leads/{lead_id}/edit", "edit_lead"),
    ("POST", "/crm/leads/{lead_id}/pipeline", "update_pipeline"),
    ("POST", "/crm/leads/{lead_id}/next-action", "update_next_action"),
    ("POST", "/crm/leads/{lead_id}/relationship-owner", "update_relationship_owner"),
    ("GET", "/crm/templates", "list_outreach_templates"),
    ("GET", "/crm/templates/new", "new_outreach_template_page"),
    ("POST", "/crm/templates", "create_outreach_template"),
    ("GET", "/crm/templates/{template_id}/edit", "edit_outreach_template_page"),
    ("POST", "/crm/templates/{template_id}/edit", "edit_outreach_template"),
    ("POST", "/crm/templates/{template_id}/approve", "approve_outreach_template"),
    ("POST", "/crm/templates/{template_id}/unapprove", "unapprove_outreach_template"),
    ("POST", "/crm/templates/{template_id}/archive", "delete_outreach_template"),
    ("GET", "/crm/templates/{template_id}/use", "use_outreach_template_page"),
    ("POST", "/crm/templates/{template_id}/use", "render_outreach_template_preview"),
    ("GET", "/crm/leads/{lead_id}/delete", "delete_lead_page"),
    ("POST", "/crm/leads/{lead_id}/delete", "delete_lead"),
    ("GET", "/settings/users/new", "new_user_page"),
    ("POST", "/settings/users/new", "create_user"),
    ("GET", "/health", "health"),
    ("GET", "/family/setup", "family_setup"),
    ("GET", "/settings/users", "users_page"),
    ("GET", "/settings/users/", "users_page"),
    ("GET", "/settings/users/{user_id}", "manage_user_page"),
    ("POST", "/settings/users/{user_id}/status", "update_user_status"),
    ("POST", "/settings/users/{user_id}/password", "update_user_password"),
    ("POST", "/settings/users/{user_id}/workspace", "update_user_workspace"),
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
    database.init_db()
    with database.get_db() as db:
        db.execute("DELETE FROM users WHERE username = ?", ("test-user",))
        db.execute(
            """
            INSERT INTO users (
                username,
                display_name,
                password_hash,
                role,
                active,
                must_change_password
            )
            VALUES (?, ?, ?, 'owner', 1, 0)
            """,
            (
                "test-user",
                "Test User",
                hash_password("test-password"),
            ),
        )

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
    assert app.version == "0.4.0-family-workspaces"


def test_windows_helper_loads_local_env_when_present():
    script = (Path(__file__).resolve().parent.parent / "run.ps1").read_text()
    assert 'Test-Path ".env"' in script
    assert '@("--env-file", ".env")' in script
    assert "python -m uvicorn @markOsUvicornArgs" in script


def test_public_health_static_and_protected_home_behavior(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / "public-health.db",
    )
    database.init_db()

    health_status, _, health_body = asyncio.run(
        _request("/health")
    )
    home_status, home_headers, _ = asyncio.run(
        _request("/")
    )
    static_status, _, _ = asyncio.run(
        _request("/static/quests.css")
    )

    health_payload = json.loads(health_body)
    assert health_status == 200
    assert health_payload["status"] == "ok"
    assert health_payload["version"] == "0.5.0-observability"
    assert health_payload["checks"]["database"]["status"] == "ok"
    assert home_status == 303
    assert _header_values(
        home_headers,
        b"location",
    ) == [b"/login?next=/"]
    assert static_status == 200


def test_login_cookie_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "login-cookie.db")
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
    assert b"max-age=604800" in normalized_cookie


def test_authenticated_pages_render_with_temporary_database(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "application.db")
    database.init_db()
    cookie, _ = _login_cookie(monkeypatch)

    # M9 quest details are private to their owning user. Create one
    # quest for the authenticated owner instead of using global ID 1.
    with database.get_db() as db:
        owner_id = db.execute(
            """
            SELECT id
            FROM users
            WHERE role = 'owner' AND active = 1
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()[0]
        quest_id = db.execute(
            """
            INSERT INTO tasks (
                user_id,
                title,
                description,
                status,
                quest_source,
                why
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                owner_id,
                "Application route fixture",
                "Owned quest used to verify the detail page.",
                "backlog",
                "manual",
                "M9 route isolation test.",
            ),
        ).lastrowid

    for target in (
        "/",
        "/quests",
        f"/quests/{quest_id}",
        "/goals",
        "/crm",
        "/crm/follow-ups",
        "/crm/leads/new",
        "/crm/effort",
        "/crm/webhooks",
        "/settings/users/new",
        "/life-os",
        "/history",
    ):
        status, _, _ = asyncio.run(_request(target, headers=[(b"cookie", cookie)]))
        assert status == 200, target


def test_owner_can_run_billing_through_the_http_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "billing-route.db")
    cookie, _ = _login_cookie(monkeypatch)

    with database.get_db() as db:
        owner_id = db.execute(
            "SELECT id FROM users WHERE role='owner' AND active=1 LIMIT 1"
        ).fetchone()[0]
        organization_id = db.execute(
            "SELECT id FROM organizations WHERE slug='mark-agency'"
        ).fetchone()[0]
        from app.services.client_delivery import onboard_client_from_lead
        from app.services.leads import create_lead

        lead = create_lead(
            db,
            company="Billing Route Co",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="Referral",
            source_url="https://example.com/billing-route",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="won",
            priority="medium",
            next_action="Kick off delivery.",
            notes="",
            created_by_user_id=owner_id,
            assigned_to_user_id=owner_id,
            organization_id=organization_id,
        ).lead
        client = onboard_client_from_lead(
            db,
            lead["id"],
            actor={"id": owner_id, "role": "owner"},
            organization_id=organization_id,
            engagement_title="Billing engagement",
        )
        engagement = db.execute(
            "SELECT id FROM client_engagements WHERE client_id = ?",
            (client["id"],),
        ).fetchone()

    invoice_status, _, _ = asyncio.run(
        _request(
            f"/crm/engagements/{engagement['id']}/billing/invoices",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode(
                {
                    "invoice_reference": "INV-ROUTE-001",
                    "invoice_date": "2026-09-01",
                    "amount": "50000.00",
                    "currency": "PHP",
                }
            ).encode(),
        )
    )
    assert invoice_status == 303

    with database.get_db() as db:
        invoice = db.execute(
            "SELECT id, row_version FROM invoices WHERE invoice_reference = ?",
            ("INV-ROUTE-001",),
        ).fetchone()
    assert invoice is not None

    payment_status, _, _ = asyncio.run(
        _request(
            f"/crm/engagements/{engagement['id']}/billing/invoices/{invoice['id']}/payments",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode(
                {
                    "amount": "50000.00",
                    "currency": "PHP",
                    "payment_date": "2026-09-05",
                }
            ).encode(),
        )
    )
    assert payment_status == 303

    with database.get_db() as db:
        # Recording a payment must never auto-flip the invoice's own status.
        reloaded_invoice = db.execute(
            "SELECT status FROM invoices WHERE id = ?", (invoice["id"],)
        ).fetchone()
    assert reloaded_invoice["status"] == "draft"

    status_update_status, _, _ = asyncio.run(
        _request(
            f"/crm/engagements/{engagement['id']}/billing/invoices/{invoice['id']}/status",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode(
                {"status": "paid", "row_version": str(invoice["row_version"])}
            ).encode(),
        )
    )
    assert status_update_status == 303

    with database.get_db() as db:
        final_invoice = db.execute(
            "SELECT status FROM invoices WHERE id = ?", (invoice["id"],)
        ).fetchone()
    assert final_invoice["status"] == "paid"


def test_relationship_manager_cannot_reach_engagement_billing(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "billing-denied.db")
    database.init_db()
    with database.get_db() as db:
        db.execute(
            """
            INSERT INTO users (
                username, display_name, password_hash,
                role, active, must_change_password
            )
            VALUES (?, ?, ?, 'relationship_manager', 1, 0)
            """,
            (
                "rm-billing-test",
                "RM Billing Test",
                hash_password("rm-billing-password-123"),
            ),
        )

    body = urlencode(
        {"username": "rm-billing-test", "password": "rm-billing-password-123"}
    ).encode()
    _, login_headers, _ = asyncio.run(
        _request(
            "/login",
            method="POST",
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            body=body,
        )
    )
    set_cookie = _header_values(login_headers, b"set-cookie")[0]
    cookie = set_cookie.split(b";", 1)[0]

    status, _, _ = asyncio.run(
        _request("/crm/engagements/1/billing", headers=[(b"cookie", cookie)])
    )
    assert status == 303


def test_owner_can_onboard_a_won_lead_through_the_http_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "onboarding-route.db")
    cookie, _ = _login_cookie(monkeypatch)

    with database.get_db() as db:
        owner_id = db.execute(
            "SELECT id FROM users WHERE role='owner' AND active=1 LIMIT 1"
        ).fetchone()[0]
        organization_id = db.execute(
            "SELECT id FROM organizations WHERE slug='mark-agency'"
        ).fetchone()[0]
        from app.services.leads import create_lead

        lead = create_lead(
            db,
            company="Onboarding Route Co",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="Referral",
            source_url="https://example.com/onboarding-route",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="won",
            priority="medium",
            next_action="Kick off delivery.",
            notes="",
            created_by_user_id=owner_id,
            assigned_to_user_id=owner_id,
            organization_id=organization_id,
        ).lead

    onboard_status, onboard_headers, _ = asyncio.run(
        _request(
            f"/crm/leads/{lead['id']}/onboard",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode({"engagement_title": "Kickoff engagement"}).encode(),
        )
    )
    assert onboard_status == 303
    client_location = _header_values(onboard_headers, b"location")[0].decode()

    with database.get_db() as db:
        client = db.execute(
            "SELECT id FROM organization_clients WHERE lead_id = ?",
            (lead["id"],),
        ).fetchone()
        engagement = db.execute(
            "SELECT id, row_version FROM client_engagements WHERE client_id = ?",
            (client["id"],),
        ).fetchone()
    assert f"/crm/clients/{client['id']}" in urlsplit(client_location).path

    item_status, item_headers, _ = asyncio.run(
        _request(
            f"/crm/engagements/{engagement['id']}/items",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode(
                {
                    "item_type": "task",
                    "title": "Set up reporting dashboard",
                    "due_date": "",
                    "assigned_to_user_id": "",
                }
            ).encode(),
        )
    )
    assert item_status == 303

    with database.get_db() as db:
        item = db.execute(
            "SELECT id, row_version FROM engagement_items WHERE engagement_id = ?",
            (engagement["id"],),
        ).fetchone()

    complete_item_status, _, _ = asyncio.run(
        _request(
            f"/crm/engagements/{engagement['id']}/items/{item['id']}/status",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode(
                {"status": "completed", "row_version": str(item["row_version"])}
            ).encode(),
        )
    )
    assert complete_item_status == 303

    complete_engagement_status, _, _ = asyncio.run(
        _request(
            f"/crm/engagements/{engagement['id']}/complete",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode({"row_version": str(engagement["row_version"])}).encode(),
        )
    )
    assert complete_engagement_status == 303

    with database.get_db() as db:
        final_item = db.execute(
            "SELECT status FROM engagement_items WHERE id = ?", (item["id"],)
        ).fetchone()
        final_engagement = db.execute(
            "SELECT status FROM client_engagements WHERE id = ?",
            (engagement["id"],),
        ).fetchone()
    assert final_item["status"] == "completed"
    assert final_engagement["status"] == "completed"

    # Onboarding the same lead again must not create a second client.
    repeat_status, _, _ = asyncio.run(
        _request(
            f"/crm/leads/{lead['id']}/onboard",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode({"engagement_title": "Duplicate attempt"}).encode(),
        )
    )
    assert repeat_status == 303
    with database.get_db() as db:
        client_count = db.execute(
            "SELECT COUNT(*) FROM organization_clients WHERE lead_id = ?",
            (lead["id"],),
        ).fetchone()[0]
    assert client_count == 1


def test_owner_can_run_a_proposal_through_the_http_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "proposal-route.db")
    cookie, _ = _login_cookie(monkeypatch)

    with database.get_db() as db:
        owner_id = db.execute(
            "SELECT id FROM users WHERE role='owner' AND active=1 LIMIT 1"
        ).fetchone()[0]
        organization_id = db.execute(
            "SELECT id FROM organizations WHERE slug='mark-agency'"
        ).fetchone()[0]
        from app.services.leads import create_lead

        lead = create_lead(
            db,
            company="Proposal Route Co",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="Referral",
            source_url="https://example.com/proposal-route",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="meeting",
            priority="medium",
            next_action="Prepare a proposal.",
            notes="",
            created_by_user_id=owner_id,
            assigned_to_user_id=owner_id,
            organization_id=organization_id,
        ).lead

    create_status, create_headers, _ = asyncio.run(
        _request(
            f"/crm/leads/{lead['id']}/proposals",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode(
                {
                    "service_offered": "Data automation retainer",
                    "engagement_type": "retainer",
                    "proposed_price": "50000.00",
                    "proposal_url": "https://docs.example.com/route-proposal",
                    "currency": "PHP",
                }
            ).encode(),
        )
    )
    assert create_status == 303
    location = _header_values(create_headers, b"location")[0].decode()

    with database.get_db() as db:
        proposal = db.execute(
            "SELECT id, status, row_version FROM proposals WHERE lead_id = ?",
            (lead["id"],),
        ).fetchone()
    assert proposal["status"] == "draft"
    assert f"/proposals/{proposal['id']}" in urlsplit(location).path

    for action, expected_status in (
        ("submit-review", "internal_review"),
        ("approve", "approved"),
        ("send", "sent"),
    ):
        with database.get_db() as db:
            row_version = db.execute(
                "SELECT row_version FROM proposals WHERE id = ?",
                (proposal["id"],),
            ).fetchone()["row_version"]

        status, _, _ = asyncio.run(
            _request(
                f"/crm/leads/{lead['id']}/proposals/{proposal['id']}/{action}",
                method="POST",
                headers=[
                    (b"cookie", cookie),
                    (b"content-type", b"application/x-www-form-urlencoded"),
                ],
                body=urlencode({"row_version": str(row_version)}).encode(),
            )
        )
        assert status == 303, action

        with database.get_db() as db:
            after = db.execute(
                "SELECT status FROM proposals WHERE id = ?",
                (proposal["id"],),
            ).fetchone()
        assert after["status"] == expected_status, action

    with database.get_db() as db:
        row_version = db.execute(
            "SELECT row_version FROM proposals WHERE id = ?",
            (proposal["id"],),
        ).fetchone()["row_version"]

    decision_status, _, _ = asyncio.run(
        _request(
            f"/crm/leads/{lead['id']}/proposals/{proposal['id']}/decision",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode(
                {"decision": "accepted", "row_version": str(row_version)}
            ).encode(),
        )
    )
    assert decision_status == 303

    with database.get_db() as db:
        final = db.execute(
            "SELECT decision_status, status FROM proposals WHERE id = ?",
            (proposal["id"],),
        ).fetchone()
        lead_after = db.execute(
            "SELECT pipeline_status FROM leads WHERE id = ?",
            (lead["id"],),
        ).fetchone()
    assert final["decision_status"] == "accepted"
    assert lead_after["pipeline_status"] == "meeting"


def test_owner_can_qualify_a_lead_through_the_http_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "qualification-route.db")
    cookie, _ = _login_cookie(monkeypatch)

    with database.get_db() as db:
        owner_id = db.execute(
            "SELECT id FROM users WHERE role='owner' AND active=1 LIMIT 1"
        ).fetchone()[0]
        organization_id = db.execute(
            "SELECT id FROM organizations WHERE slug='mark-agency'"
        ).fetchone()[0]
        from app.services.leads import create_lead

        lead = create_lead(
            db,
            company="Route Test Co",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="Referral",
            source_url="https://example.com/route-test",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="new",
            priority="medium",
            next_action="Schedule discovery call.",
            notes="",
            created_by_user_id=owner_id,
            assigned_to_user_id=owner_id,
            organization_id=organization_id,
        ).lead

    edit_status, _, _ = asyncio.run(
        _request(
            f"/crm/leads/{lead['id']}/qualification/edit",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode(
                {
                    "row_version": str(lead["row_version"]),
                    "business_problem": "Manual reporting wastes hours weekly.",
                    "urgency": "High",
                }
            ).encode(),
        )
    )
    assert edit_status == 303

    with database.get_db() as db:
        after_edit = db.execute(
            "SELECT qualification_status, row_version, business_problem "
            "FROM leads WHERE id = ?",
            (lead["id"],),
        ).fetchone()
    assert after_edit["qualification_status"] == "in_progress"
    assert after_edit["business_problem"] == "Manual reporting wastes hours weekly."

    decide_status, _, _ = asyncio.run(
        _request(
            f"/crm/leads/{lead['id']}/qualification/decide",
            method="POST",
            headers=[
                (b"cookie", cookie),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
            body=urlencode(
                {
                    "row_version": str(after_edit["row_version"]),
                    "decision": "qualified",
                }
            ).encode(),
        )
    )
    assert decide_status == 303

    with database.get_db() as db:
        after_decide = db.execute(
            "SELECT qualification_status, pipeline_status FROM leads WHERE id = ?",
            (lead["id"],),
        ).fetchone()
    assert after_decide["qualification_status"] == "qualified"
    assert after_decide["pipeline_status"] == "new"

    detail_status, _, detail_body = asyncio.run(
        _request(
            f"/crm/leads/{lead['id']}",
            headers=[(b"cookie", cookie)],
        )
    )
    assert detail_status == 200
    assert b"QUALIFIED" in detail_body.upper()


def test_owner_can_download_a_fresh_verified_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backup-download.db")
    cookie, _ = _login_cookie(monkeypatch)

    status, headers, body = asyncio.run(
        _request("/crm/backup/download", headers=[(b"cookie", cookie)])
    )

    assert status == 200
    assert _header_values(headers, b"content-type") == [
        b"application/x-sqlite3"
    ]
    assert body.startswith(b"SQLite format 3\x00")

    backup_files = list((tmp_path / "backups").glob("mark_os_*.sqlite3"))
    assert len(backup_files) == 1


def test_lead_sourcer_cannot_download_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backup-denied.db")
    database.init_db()
    with database.get_db() as db:
        db.execute(
            """
            INSERT INTO users (
                username, display_name, password_hash,
                role, active, must_change_password
            )
            VALUES (?, ?, ?, 'lead_sourcer', 1, 0)
            """,
            (
                "sourcer-user",
                "Sourcer User",
                hash_password("sourcer-password-123"),
            ),
        )

    body = urlencode(
        {
            "username": "sourcer-user",
            "password": "sourcer-password-123",
        }
    ).encode()
    _, login_headers, _ = asyncio.run(
        _request(
            "/login",
            method="POST",
            headers=[
                (b"content-type", b"application/x-www-form-urlencoded")
            ],
            body=body,
        )
    )
    set_cookie = _header_values(login_headers, b"set-cookie")[0]
    cookie = set_cookie.split(b";", 1)[0]

    status, headers, _ = asyncio.run(
        _request("/crm/backup/download", headers=[(b"cookie", cookie)])
    )
    assert status == 303
    assert _header_values(headers, b"location") == [b"/crm?error=forbidden"]


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

    with database.get_db() as db:
        edit_version = int(
            db.execute("SELECT row_version FROM leads WHERE id = 1").fetchone()[
                "row_version"
            ]
        )

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
            "row_version": str(edit_version),
        },
        cookie=cookie,
    )
    with database.get_db() as db:
        pipeline_version = int(
            db.execute("SELECT row_version FROM leads WHERE id = 1").fetchone()[
                "row_version"
            ]
        )

    pipeline_status, pipeline_headers, _ = _post_form(
        "/crm/leads/1/pipeline",
        {
            "pipeline_status": "replied",
            "row_version": str(pipeline_version),
        },
        cookie=cookie,
    )
    with database.get_db() as db:
        next_action_version = int(
            db.execute("SELECT row_version FROM leads WHERE id = 1").fetchone()[
                "row_version"
            ]
        )

    next_action_status, next_action_headers, _ = _post_form(
        "/crm/leads/1/next-action",
        {
            "next_action": "Book a discovery call",
            "next_action_due_date": "2026-08-08",
            "row_version": str(next_action_version),
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
                   next_action, next_action_due_date, quest_id, deleted_at,
                   row_version
            FROM leads WHERE id = 1
            """
        ).fetchone()
        lead_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        quest = db.execute(
            "SELECT id, title FROM tasks WHERE id = ?",
            (lead_before_delete["quest_id"],),
        ).fetchone()

    assert lead_count == 1
    assert tuple(lead_before_delete)[:8] == (
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
        {
            "confirmation": "DELETE",
            "row_version": str(lead_before_delete["row_version"]),
        },
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
