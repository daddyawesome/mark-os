from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import Request
from fastapi.responses import PlainTextResponse

from app import database
import app.main as main_module
from app.services.access_control import (
    can_access_request,
    landing_path_for_user,
    permitted_destination,
)
from app.services.lead_csv_import import import_leads_from_csv


OWNER = {
    "id": 1,
    "username": "mark",
    "display_name": "Mark",
    "role": "owner",
}

LEAD_SOURCER = {
    "id": 2,
    "username": "brother",
    "display_name": "Brother",
    "role": "lead_sourcer",
}


def test_owner_keeps_full_mark_os_access():
    cases = (
        ("GET", "/"),
        ("GET", "/quests"),
        ("POST", "/quests"),
        ("GET", "/history"),
        ("POST", "/check-in"),
        ("GET", "/crm"),
        ("POST", "/crm/leads/1/pipeline"),
        ("POST", "/crm/leads/1/outreach/approve"),
        ("POST", "/crm/leads/1/delete"),
    )
    assert all(
        can_access_request(OWNER, method, path)
        for method, path in cases
    )
    assert landing_path_for_user(OWNER) == "/"


def test_lead_sourcer_has_small_read_and_intake_surface():
    allowed = (
        ("GET", "/crm"),
        ("HEAD", "/crm"),
        ("GET", "/crm/leads/new"),
        ("GET", "/crm/leads/import/template"),
        ("GET", "/crm/leads/1"),
        ("GET", "/crm/leads/999"),
        ("GET", "/crm/leads/1/research/edit"),
        ("POST", "/crm/leads/1/research/edit"),
        ("POST", "/crm/leads"),
        ("POST", "/crm/leads/import"),
        ("POST", "/logout"),
    )
    denied = (
        ("GET", "/"),
        ("GET", "/quests"),
        ("GET", "/goals"),
        ("GET", "/life-os"),
        ("GET", "/history"),
        ("POST", "/check-in"),
        ("GET", "/crm/leads/1/edit"),
        ("POST", "/crm/leads/1/edit"),
        ("POST", "/crm/leads/1/pipeline"),
        ("POST", "/crm/leads/1/outreach/approve"),
        ("POST", "/crm/leads/1/next-action"),
        ("GET", "/crm/leads/1/delete"),
        ("POST", "/crm/leads/1/delete"),
        ("DELETE", "/crm/leads/1"),
    )

    assert all(
        can_access_request(LEAD_SOURCER, method, path)
        for method, path in allowed
    )
    assert not any(
        can_access_request(LEAD_SOURCER, method, path)
        for method, path in denied
    )
    assert landing_path_for_user(LEAD_SOURCER) == "/crm"


def test_lead_sourcer_login_destination_stays_inside_crm():
    assert permitted_destination(LEAD_SOURCER, "/crm") == "/crm"
    assert (
        permitted_destination(LEAD_SOURCER, "/crm/leads/new")
        == "/crm/leads/new"
    )
    assert permitted_destination(LEAD_SOURCER, "/") == "/crm"
    assert permitted_destination(LEAD_SOURCER, "/quests") == "/crm"


def test_unknown_roles_receive_no_authenticated_permissions():
    unknown = {
        "id": 7,
        "username": "unknown",
        "display_name": "Unknown",
        "role": "administrator",
    }
    assert not can_access_request(unknown, "GET", "/crm")
    assert not can_access_request(None, "GET", "/crm")


def test_sourcer_csv_import_forces_new_pipeline_status(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "m3-csv.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    monkeypatch.delenv("MARK_OS_PASSWORD", raising=False)
    database.init_db()

    csv_content = (
        "Company,Contact person,Job title,Source,Source link,"
        "Problem or opportunity,Why Mark fits,Pipeline status,"
        "Priority,Next action,Due date,Notes\n"
        "Potential Client,Alex Buyer,Founder,LinkedIn,"
        "https://example.com,Needs reporting help,"
        "Mark builds data systems,Won,High,Review the lead,"
        "2026-08-10,Imported by lead sourcer\n"
    ).encode("utf-8")

    with database.get_db() as db:
        result = import_leads_from_csv(
            db,
            csv_content,
            pipeline_status_override="new",
        )
        lead = db.execute(
            """
            SELECT pipeline_status, priority, quest_id
            FROM leads
            WHERE company = 'Potential Client'
            """
        ).fetchone()
        quest = db.execute(
            "SELECT xp_reward FROM tasks WHERE id = ?",
            (lead["quest_id"],),
        ).fetchone()

    assert result.created_count == 1
    assert result.invalid_count == 0
    assert lead["pipeline_status"] == "new"
    assert lead["priority"] == "high"
    assert quest["xp_reward"] == 0


def test_role_aware_templates_hide_owner_controls():
    project_root = Path(__file__).resolve().parent.parent

    base = (project_root / "app/templates/base.html").read_text(
        encoding="utf-8"
    )
    dashboard = (
        project_root / "app/templates/client_hunting.html"
    ).read_text(encoding="utf-8")
    intake = (project_root / "app/templates/add_leads.html").read_text(
        encoding="utf-8"
    )
    detail = (project_root / "app/templates/lead_detail.html").read_text(
        encoding="utf-8"
    )
    fields = (
        project_root / "app/templates/partials/lead_form_fields.html"
    ).read_text(encoding="utf-8")

    assert "request.state.current_user.role == 'owner'" in base
    assert "LEAD SOURCER" not in base
    assert "Lead Researcher access" in dashboard
    assert "{% if can_manage_crm %}<th>Quest</th>{% endif %}" in dashboard
    assert "saved as <strong>New</strong>" in intake
    assert "{% if can_manage_crm %}" in detail
    assert "Read-only review" in detail
    assert 'name="pipeline_status" value="new"' in fields



def _request(method: str, path: str) -> Request:
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


def test_permission_middleware_redirects_private_sourcer_gets(
    monkeypatch,
):
    monkeypatch.setattr(
        main_module,
        "current_user",
        lambda request: LEAD_SOURCER,
    )

    async def call_next(request):
        return PlainTextResponse("allowed")

    response = asyncio.run(
        main_module.login_and_permission_guard(
            _request("GET", "/quests"),
            call_next,
        )
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/crm?error=forbidden"


def test_permission_middleware_rejects_sourcer_mutations(
    monkeypatch,
):
    monkeypatch.setattr(
        main_module,
        "current_user",
        lambda request: LEAD_SOURCER,
    )

    async def call_next(request):
        return PlainTextResponse("should not run")

    response = asyncio.run(
        main_module.login_and_permission_guard(
            _request("POST", "/crm/leads/1/pipeline"),
            call_next,
        )
    )

    assert response.status_code == 403
    assert response.body == b"Forbidden"


def test_permission_middleware_allows_sourcer_crm_intake(
    monkeypatch,
):
    monkeypatch.setattr(
        main_module,
        "current_user",
        lambda request: LEAD_SOURCER,
    )
    observed = {}

    async def call_next(request):
        observed["user"] = request.state.current_user
        return PlainTextResponse("allowed")

    response = asyncio.run(
        main_module.login_and_permission_guard(
            _request("POST", "/crm/leads"),
            call_next,
        )
    )

    assert response.status_code == 200
    assert response.body == b"allowed"
    assert observed["user"] == LEAD_SOURCER
