from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from app import database
from app.routes import client_hunting
from app.services.follow_up_command_center import build_follow_up_command_center
from app.services.lead_activities import (
    LeadActivityNotFoundError,
    create_activity,
    list_lead_activities,
)
from app.services.lead_pipeline_workflow import change_pipeline_stage
from app.services.lead_research_workflow import list_research_review_queue
from app.services.lead_work_queues import list_visible_leads
from app.services.leads import create_lead
from app.services.relationship_manager import list_active_relationship_managers
from app.services.team_users import (
    create_lead_sourcer,
    create_relationship_manager,
    get_primary_owner_id,
)
from app.services.workspace_context import authorized_workspaces


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _workspace(db, slug: str, membership_role: str = "workspace_admin") -> dict:
    row = db.execute(
        "SELECT id, slug, name FROM organizations WHERE slug = ?",
        (slug,),
    ).fetchone()
    return {
        "id": int(row["id"]),
        "slug": row["slug"],
        "name": row["name"],
        "membership_role": membership_role,
    }


def _request(user: dict, workspace: dict | None, path: str) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    request.state.current_user = user
    request.state.current_workspace = workspace
    request.state.authorized_workspaces = [workspace]
    return request


@pytest.fixture
def workspace_crm(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "workspace-crm.db")
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db)
        assert owner_id is not None
        owner = dict(
            db.execute(
                "SELECT id, username, display_name, role, active FROM users WHERE id = ?",
                (owner_id,),
            ).fetchone()
        )
        mark_workspace = _workspace(db, "mark-agency")
        pendang_workspace = _workspace(db, "pendang")

        mark_sourcer = dict(
            create_lead_sourcer(
                db,
                username="mark-researcher",
                display_name="MARK Researcher",
                password="temporary-pass-123",
                password_confirmation="temporary-pass-123",
            )
        )
        pendang_sourcer = dict(
            create_lead_sourcer(
                db,
                username="pendang-researcher",
                display_name="Pendang Researcher",
                password="temporary-pass-456",
                password_confirmation="temporary-pass-456",
                workspace_slug="pendang",
            )
        )
        mark_manager = dict(
            create_relationship_manager(
                db,
                username="mark-manager",
                display_name="MARK Manager",
                password="temporary-pass-789",
                password_confirmation="temporary-pass-789",
            )
        )
        pendang_manager = dict(
            create_relationship_manager(
                db,
                username="pendang-manager",
                display_name="Pendang Manager",
                password="temporary-pass-012",
                password_confirmation="temporary-pass-012",
                workspace_slug="pendang",
            )
        )

        mark_lead = create_lead(
            db,
            company="MARK Workspace Lead",
            contact_person="Agency Buyer",
            source="LinkedIn",
            problem_opportunity="MARK-only opportunity.",
            why_mark_fits="Agency delivery fit.",
            next_action="Follow up with MARK lead.",
            next_action_due_date="2026-08-07",
            request_key="workspace-4b-mark-lead",
            created_by_user_id=mark_sourcer["id"],
            assigned_to_user_id=mark_sourcer["id"],
            business_development_owner_user_id=mark_manager["id"],
            organization_id=mark_workspace["id"],
        ).lead
        pendang_lead = create_lead(
            db,
            company="Pendang Workspace Lead",
            contact_person="Pendang Buyer",
            source="Referral",
            problem_opportunity="Pendang-only opportunity.",
            why_mark_fits="Pendang research fit.",
            next_action="Follow up with Pendang lead.",
            next_action_due_date="2026-08-07",
            request_key="workspace-4b-pendang-lead",
            created_by_user_id=pendang_sourcer["id"],
            assigned_to_user_id=pendang_sourcer["id"],
            business_development_owner_user_id=pendang_manager["id"],
            organization_id=pendang_workspace["id"],
        ).lead

    return {
        "owner": owner,
        "mark_workspace": mark_workspace,
        "pendang_workspace": pendang_workspace,
        "mark_sourcer": mark_sourcer,
        "pendang_sourcer": pendang_sourcer,
        "mark_manager": mark_manager,
        "pendang_manager": pendang_manager,
        "mark_lead_id": int(mark_lead["id"]),
        "pendang_lead_id": int(pendang_lead["id"]),
    }


def test_legacy_unscoped_crm_staff_are_backfilled_only_to_mark_agency(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "legacy-membership.db")
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        legacy_id = db.execute(
            """
            INSERT INTO users (username, display_name, password_hash, role, active)
            VALUES ('legacy-researcher', 'Legacy Researcher', 'hash', 'lead_sourcer', 1)
            """
        ).lastrowid
        pendang_only_id = db.execute(
            """
            INSERT INTO users (username, display_name, password_hash, role, active)
            VALUES ('pendang-only', 'Pendang Only', 'hash', 'lead_sourcer', 1)
            """
        ).lastrowid
        pendang_id = db.execute(
            "SELECT id FROM organizations WHERE slug = 'pendang'"
        ).fetchone()["id"]
        db.execute(
            """
            INSERT INTO organization_memberships
                (user_id, organization_id, membership_role)
            VALUES (?, ?, 'crm_contributor')
            """,
            (pendang_only_id, pendang_id),
        )

    database.init_db()
    database.init_db()

    with database.get_db() as db:
        legacy = authorized_workspaces(db, legacy_id)
        pendang_only = authorized_workspaces(db, pendang_only_id)

    assert [(row["slug"], row["membership_role"]) for row in legacy] == [
        ("mark-agency", "crm_contributor")
    ]
    assert [(row["slug"], row["membership_role"]) for row in pendang_only] == [
        ("pendang", "crm_contributor")
    ]


def test_new_crm_staff_can_be_created_in_an_explicit_workspace(workspace_crm):
    context = workspace_crm
    with database.get_db() as db:
        mark_workspaces = authorized_workspaces(db, context["mark_sourcer"]["id"])
        pendang_workspaces = authorized_workspaces(
            db,
            context["pendang_sourcer"]["id"],
        )

    assert [(row["slug"], row["membership_role"]) for row in mark_workspaces] == [
        ("mark-agency", "crm_contributor")
    ]
    assert [(row["slug"], row["membership_role"]) for row in pendang_workspaces] == [
        ("pendang", "crm_contributor")
    ]


def test_explicit_workspace_service_access_requires_membership(workspace_crm):
    context = workspace_crm
    with database.get_db() as db:
        with pytest.raises(PermissionError):
            list_visible_leads(
                db,
                context["pendang_sourcer"],
                organization_id=context["mark_workspace"]["id"],
            )

        visible = list_visible_leads(
            db,
            context["pendang_sourcer"],
            organization_id=context["pendang_workspace"]["id"],
        )

    assert [row["company"] for row in visible] == ["Pendang Workspace Lead"]


def test_owner_crm_dashboard_renders_only_the_active_workspace(workspace_crm):
    context = workspace_crm

    mark_page = client_hunting.crm_dashboard(
        _request(
            context["owner"],
            context["mark_workspace"],
            "/crm",
        )
    )
    pendang_page = client_hunting.crm_dashboard(
        _request(
            context["owner"],
            context["pendang_workspace"],
            "/crm",
        )
    )

    mark_body = mark_page.body.decode("utf-8")
    pendang_body = pendang_page.body.decode("utf-8")

    assert "MARK Workspace Lead" in mark_body
    assert "Pendang Workspace Lead" not in mark_body
    assert "Pendang Workspace Lead" in pendang_body
    assert "MARK Workspace Lead" not in pendang_body


def test_direct_cross_workspace_lead_url_returns_safe_404(workspace_crm):
    context = workspace_crm

    with pytest.raises(HTTPException) as exc_info:
        client_hunting.lead_detail(
            _request(
                context["owner"],
                context["mark_workspace"],
                f"/crm/leads/{context['pendang_lead_id']}",
            ),
            context["pendang_lead_id"],
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Lead not found"

    page = client_hunting.lead_detail(
        _request(
            context["owner"],
            context["pendang_workspace"],
            f"/crm/leads/{context['pendang_lead_id']}",
        ),
        context["pendang_lead_id"],
    )
    assert page.status_code == 200
    assert "Pendang Workspace Lead" in page.body.decode("utf-8")


def test_follow_up_command_center_is_workspace_scoped(workspace_crm):
    context = workspace_crm
    with database.get_db() as db:
        mark_center = build_follow_up_command_center(
            db,
            context["owner"],
            organization_id=context["mark_workspace"]["id"],
            today=__import__("datetime").date(2026, 8, 7),
        )
        pendang_center = build_follow_up_command_center(
            db,
            context["owner"],
            organization_id=context["pendang_workspace"]["id"],
            today=__import__("datetime").date(2026, 8, 7),
        )

    mark_ids = {
        lead["id"]
        for queue in mark_center["queues"]
        for lead in queue["leads"]
    }
    pendang_ids = {
        lead["id"]
        for queue in pendang_center["queues"]
        for lead in queue["leads"]
    }

    assert context["mark_lead_id"] in mark_ids
    assert context["pendang_lead_id"] not in mark_ids
    assert context["pendang_lead_id"] in pendang_ids
    assert context["mark_lead_id"] not in pendang_ids


def test_research_review_queue_is_workspace_scoped(workspace_crm):
    context = workspace_crm
    with database.get_db() as db:
        db.execute(
            "UPDATE leads SET research_status = 'ready_for_review' WHERE id IN (?, ?)",
            (context["mark_lead_id"], context["pendang_lead_id"]),
        )
        mark_queue = list_research_review_queue(
            db,
            organization_id=context["mark_workspace"]["id"],
        )
        pendang_queue = list_research_review_queue(
            db,
            organization_id=context["pendang_workspace"]["id"],
        )

    assert [row["id"] for row in mark_queue] == [context["mark_lead_id"]]
    assert [row["id"] for row in pendang_queue] == [context["pendang_lead_id"]]


def test_activity_and_pipeline_operations_cannot_cross_workspace(workspace_crm):
    context = workspace_crm
    with database.get_db() as db:
        activity = create_activity(
            db,
            context["pendang_lead_id"],
            actor=context["owner"],
            activity_type="research_started",
            activity_at="2026-08-07T09:00",
            channel="internal",
            message_summary="Pendang-only research activity.",
            organization_id=context["pendang_workspace"]["id"],
        )
        assert activity["lead_id"] == context["pendang_lead_id"]

        with pytest.raises(LeadActivityNotFoundError):
            list_lead_activities(
                db,
                context["pendang_lead_id"],
                actor=context["owner"],
                organization_id=context["mark_workspace"]["id"],
            )

        with pytest.raises(ValueError, match="active CRM user"):
            create_activity(
                db,
                context["pendang_lead_id"],
                actor=context["owner"],
                activity_type="email_sent",
                activity_at="2026-08-07T10:00",
                channel="email",
                message_summary="Forged cross-workspace attribution.",
                performed_by_user_id=context["mark_manager"]["id"],
                responsible_user_id=context["mark_manager"]["id"],
                response_status="awaiting_reply",
                next_follow_up_date="2026-08-10",
                organization_id=context["pendang_workspace"]["id"],
            )

        with pytest.raises(ValueError, match="Lead not found"):
            change_pipeline_stage(
                db,
                context["pendang_lead_id"],
                actor=context["owner"],
                pipeline_status="reviewed",
                organization_id=context["mark_workspace"]["id"],
            )


def test_relationship_manager_choices_are_workspace_scoped(workspace_crm):
    context = workspace_crm
    with database.get_db() as db:
        mark_choices = list_active_relationship_managers(
            db,
            organization_id=context["mark_workspace"]["id"],
        )
        pendang_choices = list_active_relationship_managers(
            db,
            organization_id=context["pendang_workspace"]["id"],
        )

    assert [item["username"] for item in mark_choices] == ["mark-manager"]
    assert [item["username"] for item in pendang_choices] == ["pendang-manager"]


def test_crm_entry_routes_fail_closed_without_resolved_workspace(workspace_crm):
    context = workspace_crm
    request = _request(context["mark_sourcer"], None, "/crm")

    for route_call in (
        lambda: client_hunting.crm_dashboard(request),
        lambda: client_hunting.new_lead_page(request),
        lambda: client_hunting.download_lead_csv_template(request),
    ):
        with pytest.raises(HTTPException) as exc_info:
            route_call()
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "An authorized CRM workspace is required"


def test_crm_route_fails_closed_when_middleware_has_no_authorized_workspace(
    workspace_crm,
):
    context = workspace_crm
    request = _request(
        context["owner"],
        context["mark_workspace"],
        "/crm",
    )
    request.state.current_workspace = None

    with pytest.raises(HTTPException) as exc_info:
        client_hunting.crm_dashboard(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "An authorized CRM workspace is required"
