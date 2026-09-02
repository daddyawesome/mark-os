from __future__ import annotations

import sqlite3

import pytest
from fastapi import Request

from app import auth, database
from app.db import organizations
from app.services.access_control import can_access_request
from app.services.lead_pipeline_workflow import approve_outreach, change_pipeline_stage
from app.services.lead_research_permissions import LeadPermissionError
from app.services.lead_research_workflow import (
    review_research,
    submit_research_for_review,
    update_research_details,
)
from app.services.lead_work_queues import (
    build_role_aware_crm_dashboard,
    list_visible_leads,
)
from app.services.leads import create_lead, delete_lead, get_lead
from app.services.relationship_manager import (
    assign_relationship_manager,
    list_active_relationship_managers,
    load_relationship_manager_dashboard,
)
from app.services.team_users import (
    create_lead_sourcer,
    create_relationship_manager,
    get_primary_owner_id,
    get_user_for_management,
    set_workspace_membership,
)
from app.services.users import authenticate_user
from app.services.workspace_context import authorized_workspaces


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _request_with_session() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/crm",
            "raw_path": b"/crm",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "session": {},
        }
    )


@pytest.fixture
def pendang_team(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "pendang-authority.db")
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db, active_only=True)
        assert owner_id is not None
        owner = dict(
            db.execute(
                "SELECT id, username, display_name, role, active, session_version "
                "FROM users WHERE id = ?",
                (owner_id,),
            ).fetchone()
        )
        mark_id = db.execute(
            "SELECT id FROM organizations WHERE slug = 'mark-agency'"
        ).fetchone()["id"]
        pendang_id = db.execute(
            "SELECT id FROM organizations WHERE slug = 'pendang'"
        ).fetchone()["id"]

        rey = create_relationship_manager(
            db,
            username="rey",
            display_name="Rey",
            password="rey-temp-pass-123",
            password_confirmation="rey-temp-pass-123",
            workspace_slug="pendang",
            membership_role="workspace_owner",
        )
        freddy = create_lead_sourcer(
            db,
            username="freddy",
            display_name="Freddy",
            password="freddy-temp-pass-456",
            password_confirmation="freddy-temp-pass-456",
            workspace_slug="pendang",
        )
        mark_researcher = create_lead_sourcer(
            db,
            username="mark-researcher",
            display_name="MARK Researcher",
            password="mark-research-pass-789",
            password_confirmation="mark-research-pass-789",
            workspace_slug="mark-agency",
        )

    return {
        "owner": owner,
        "mark_id": int(mark_id),
        "pendang_id": int(pendang_id),
        "rey": rey,
        "freddy": freddy,
        "mark_researcher": mark_researcher,
    }


def test_membership_active_migration_is_additive_idempotent_and_constrained():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE organization_memberships (
            user_id INTEGER NOT NULL,
            organization_id INTEGER NOT NULL,
            membership_role TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, organization_id)
        )
        """
    )
    db.execute(
        "INSERT INTO organization_memberships "
        "(user_id, organization_id, membership_role) VALUES (1, 2, 'crm_contributor')"
    )

    organizations.migrate(db)
    organizations.migrate(db)

    columns = {
        row["name"] for row in db.execute("PRAGMA table_info(organization_memberships)")
    }
    row = db.execute(
        "SELECT active FROM organization_memberships WHERE user_id = 1"
    ).fetchone()
    assert "active" in columns
    assert row["active"] == 1
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE organization_memberships SET active = 2 WHERE user_id = 1"
        )


def test_pendang_role_model_is_separate_from_global_owner(pendang_team):
    context = pendang_team
    with database.get_db() as db:
        owner_workspaces = authorized_workspaces(db, context["owner"]["id"])
        rey_workspaces = authorized_workspaces(db, context["rey"]["id"])
        freddy_workspaces = authorized_workspaces(db, context["freddy"]["id"])

    assert context["rey"]["role"] == "relationship_manager"
    assert context["rey"]["role"] != "owner"
    assert context["freddy"]["role"] == "lead_sourcer"
    assert [(w["slug"], w["membership_role"]) for w in owner_workspaces] == [
        ("mark-agency", "workspace_admin"),
        ("pendang", "workspace_admin"),
    ]
    assert [(w["slug"], w["membership_role"]) for w in rey_workspaces] == [
        ("pendang", "workspace_owner")
    ]
    assert [(w["slug"], w["membership_role"]) for w in freddy_workspaces] == [
        ("pendang", "crm_contributor")
    ]


def test_workspace_owner_manager_gets_crm_owner_routes_but_not_global_admin(pendang_team):
    context = pendang_team
    rey = {
        **context["rey"],
        "current_workspace": {
            "id": context["pendang_id"],
            "slug": "pendang",
            "name": "Pendang Research & Analytics",
            "membership_role": "workspace_owner",
        },
    }

    allowed = (
        ("GET", "/crm"),
        ("GET", "/crm/research-review"),
        ("GET", "/crm/leads/1/edit"),
        ("POST", "/crm/leads/1/edit"),
        ("POST", "/crm/leads/1/research/review"),
        ("POST", "/crm/leads/1/outreach/approve"),
        ("POST", "/crm/leads/1/pipeline"),
        ("POST", "/crm/leads/1/relationship-owner"),
        ("GET", "/crm/leads/1/delete"),
        ("POST", "/crm/leads/1/delete"),
        ("GET", "/crm/templates"),
        ("GET", "/crm/templates/new"),
        ("POST", "/crm/templates"),
        ("GET", "/crm/templates/1/edit"),
        ("POST", "/crm/templates/1/edit"),
        ("POST", "/crm/templates/1/approve"),
        ("POST", "/crm/templates/1/unapprove"),
        ("POST", "/crm/templates/1/archive"),
        ("GET", "/crm/templates/1/use"),
        ("POST", "/crm/templates/1/use"),
    )
    denied = (
        ("GET", "/"),
        ("GET", "/quests"),
        ("GET", "/settings/users"),
        ("POST", "/settings/users/2/status"),
        ("GET", "/history"),
    )
    assert all(can_access_request(rey, method, path) for method, path in allowed)
    assert not any(can_access_request(rey, method, path) for method, path in denied)



def test_rey_workspace_owner_dashboard_sees_all_pendang_leads(pendang_team):
    context = pendang_team
    with database.get_db() as db:
        lead = create_lead(
            db,
            company="Unassigned Pendang Lead",
            contact_person="Dana Buyer",
            source="Website",
            problem_opportunity="Needs research",
            why_mark_fits="Pendang fit",
            next_action="Research",
            created_by_user_id=context["freddy"]["id"],
            assigned_to_user_id=context["freddy"]["id"],
            organization_id=context["pendang_id"],
        ).lead
        crm_dashboard = build_role_aware_crm_dashboard(
            db,
            context["rey"],
            organization_id=context["pendang_id"],
        )
        relationship_dashboard = load_relationship_manager_dashboard(
            db,
            context["rey"],
            organization_id=context["pendang_id"],
        )

    assert crm_dashboard["queue_mode"] == "owner"
    assert int(lead["id"]) in {row["id"] for row in crm_dashboard["leads"]}
    relationship_ids = {
        row["id"]
        for queue in relationship_dashboard["queues"]
        for row in queue["leads"]
    }
    assert int(lead["id"]) in relationship_ids

def test_freddy_cannot_be_promoted_to_workspace_owner(pendang_team):
    context = pendang_team
    with database.get_db() as db:
        with pytest.raises(ValueError, match="Lead Researchers"):
            set_workspace_membership(
                db,
                target_user_id=context["freddy"]["id"],
                acting_user_id=context["owner"]["id"],
                workspace_slug="pendang",
                membership_role="workspace_owner",
                active=True,
            )


def test_rey_can_review_approve_and_move_freddy_lead_inside_pendang(pendang_team):
    context = pendang_team
    with database.get_db() as db:
        result = create_lead(
            db,
            company="Pendang Prospect",
            contact_person="Ari Buyer",
            source="Referral",
            problem_opportunity="Needs analytics support",
            why_mark_fits="Pendang can research and qualify the opportunity",
            next_action="Complete research",
            created_by_user_id=context["freddy"]["id"],
            assigned_to_user_id=context["freddy"]["id"],
            business_development_owner_user_id=context["rey"]["id"],
            organization_id=context["pendang_id"],
        )
        lead_id = int(result.lead["id"])

        update_research_details(
            db,
            lead_id,
            actor=context["freddy"],
            company="Pendang Prospect",
            contact_person="Ari Buyer",
            source="Referral",
            problem_opportunity="Needs analytics support",
            why_mark_fits="Pendang can research and qualify the opportunity",
            next_action="Submit research",
            notes="Research evidence complete.",
            organization_id=context["pendang_id"],
        )
        submit_research_for_review(
            db,
            lead_id,
            actor=context["freddy"],
            organization_id=context["pendang_id"],
        )
        reviewed = review_research(
            db,
            lead_id,
            actor=context["rey"],
            decision="approved",
            review_notes="Ready for outreach.",
            organization_id=context["pendang_id"],
        )
        assert reviewed["reviewed_by_user_id"] == context["rey"]["id"]

        approved = approve_outreach(
            db,
            lead_id,
            actor=context["rey"],
            organization_id=context["pendang_id"],
        )
        assert approved["outreach_approved_by_user_id"] == context["rey"]["id"]

        moved = change_pipeline_stage(
            db,
            lead_id,
            actor=context["rey"],
            pipeline_status="reviewed",
            organization_id=context["pendang_id"],
        )
        assert moved["pipeline_status"] == "reviewed"

        assigned = assign_relationship_manager(
            db,
            lead_id,
            actor=context["rey"],
            relationship_manager_user_id=context["rey"]["id"],
            organization_id=context["pendang_id"],
        )
        assert assigned["business_development_owner_user_id"] == context["rey"]["id"]

        archived = delete_lead(
            db,
            lead_id,
            actor=context["rey"],
            confirmed=True,
            organization_id=context["pendang_id"],
        )
        assert archived["deleted_at"] is not None


def test_freddy_cannot_review_approve_move_or_archive_his_own_research(pendang_team):
    context = pendang_team
    with database.get_db() as db:
        result = create_lead(
            db,
            company="Freddy Restricted Prospect",
            contact_person="Kai Buyer",
            source="LinkedIn",
            problem_opportunity="Needs a research brief",
            why_mark_fits="Pendang can qualify the need",
            next_action="Research",
            created_by_user_id=context["freddy"]["id"],
            assigned_to_user_id=context["freddy"]["id"],
            organization_id=context["pendang_id"],
        )
        lead_id = int(result.lead["id"])
        db.execute(
            "UPDATE leads SET research_status = 'ready_for_review' WHERE id = ?",
            (lead_id,),
        )

        with pytest.raises(LeadPermissionError):
            review_research(
                db,
                lead_id,
                actor=context["freddy"],
                decision="approved",
                organization_id=context["pendang_id"],
            )
        db.execute(
            "UPDATE leads SET research_status = 'approved' WHERE id = ?",
            (lead_id,),
        )
        with pytest.raises(LeadPermissionError):
            approve_outreach(
                db,
                lead_id,
                actor=context["freddy"],
                organization_id=context["pendang_id"],
            )
        with pytest.raises(LeadPermissionError):
            change_pipeline_stage(
                db,
                lead_id,
                actor=context["freddy"],
                pipeline_status="reviewed",
                organization_id=context["pendang_id"],
            )
        with pytest.raises(LeadPermissionError):
            delete_lead(
                db,
                lead_id,
                actor=context["freddy"],
                confirmed=True,
                organization_id=context["pendang_id"],
            )


def test_rey_and_freddy_cannot_cross_into_mark_agency(pendang_team):
    context = pendang_team
    with database.get_db() as db:
        mark_lead = create_lead(
            db,
            company="MARK Only Prospect",
            contact_person="Morgan Buyer",
            source="Website",
            problem_opportunity="MARK Agency only",
            why_mark_fits="MARK Agency fit",
            next_action="Review",
            created_by_user_id=context["mark_researcher"]["id"],
            assigned_to_user_id=context["owner"]["id"],
            organization_id=context["mark_id"],
        ).lead

        for actor in (context["rey"], context["freddy"]):
            with pytest.raises(PermissionError):
                list_visible_leads(
                    db,
                    actor,
                    organization_id=context["mark_id"],
                )
            with pytest.raises(LeadPermissionError):
                change_pipeline_stage(
                    db,
                    int(mark_lead["id"]),
                    actor=actor,
                    pipeline_status="reviewed",
                    organization_id=context["mark_id"],
                )


def test_revoking_membership_invalidates_session_and_removes_operational_access(pendang_team):
    context = pendang_team
    with database.get_db() as db:
        lead = create_lead(
            db,
            company="Revocation Prospect",
            contact_person="Lee Buyer",
            source="Referral",
            problem_opportunity="Needs research",
            why_mark_fits="Pendang fit",
            next_action="Research",
            created_by_user_id=context["freddy"]["id"],
            assigned_to_user_id=context["freddy"]["id"],
            business_development_owner_user_id=context["rey"]["id"],
            organization_id=context["pendang_id"],
        ).lead
        freddy_login = authenticate_user(db, "freddy", "freddy-temp-pass-456")
        before = get_user_for_management(db, context["freddy"]["id"])

    request = _request_with_session()
    auth.sign_in(request, freddy_login)
    assert auth.current_user(request) is not None

    with database.get_db() as db:
        revoked = set_workspace_membership(
            db,
            target_user_id=context["freddy"]["id"],
            acting_user_id=context["owner"]["id"],
            workspace_slug="pendang",
            membership_role="crm_contributor",
            active=False,
        )
        after = get_user_for_management(db, context["freddy"]["id"])
        refreshed_lead = get_lead(
            db,
            int(lead["id"]),
            organization_id=context["pendang_id"],
        )
        workspaces = authorized_workspaces(db, context["freddy"]["id"])

    assert revoked["active"] == 0
    assert after["session_version"] == before["session_version"] + 1
    assert workspaces == []
    assert refreshed_lead["assigned_to_user_id"] == context["owner"]["id"]
    assert auth.current_user(request) is None

    # Startup compatibility seeding must not silently restore revoked access.
    database.init_db()
    with database.get_db() as db:
        assert authorized_workspaces(db, context["freddy"]["id"]) == []


def test_revoked_relationship_manager_disappears_from_workspace_choices(pendang_team):
    context = pendang_team
    with database.get_db() as db:
        before = list_active_relationship_managers(
            db, organization_id=context["pendang_id"]
        )
        assert [row["username"] for row in before] == ["rey"]

        set_workspace_membership(
            db,
            target_user_id=context["rey"]["id"],
            acting_user_id=context["owner"]["id"],
            workspace_slug="pendang",
            membership_role="workspace_owner",
            active=False,
        )
        after = list_active_relationship_managers(
            db, organization_id=context["pendang_id"]
        )

    assert after == []
