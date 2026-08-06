from __future__ import annotations

from datetime import date
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from app import database
from app.routes import client_hunting
from app.services.access_control import can_access_request
from app.services.follow_up_command_center import (
    build_follow_up_command_center as build_command_center,
)
from app.services.lead_activities import create_activity
from app.services.leads import create_lead
from app.services.team_users import (
    create_lead_sourcer,
    create_relationship_manager,
    get_primary_owner_id,
)


TODAY = date(2026, 8, 6)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv(
        "MARK_OS_PASSWORD",
        "owner-password-123",
    )
    monkeypatch.setenv(
        "MARK_OS_DISPLAY_NAME",
        "Mark",
    )


def _request(
    user: dict,
    *,
    path: str = "/crm/follow-ups",
    query_string: str = "",
) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "headers": [],
            "query_string": query_string.encode(),
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    request.state.current_user = user
    return request


def _lead(
    db,
    *,
    company: str,
    creator_id: int,
    assignee_id: int,
    business_owner_id: int | None = None,
    due_date: str | None = None,
    pipeline_status: str = "new",
) -> dict:
    lead = create_lead(
        db,
        company=company,
        contact_person="Alex Buyer",
        job_title="Founder",
        source="LinkedIn",
        source_url="https://example.com/" + company.casefold().replace(" ", "-"),
        problem_opportunity="Follow-up needs a deterministic queue.",
        why_mark_fits="Mark can build the operating workflow.",
        pipeline_status="new",
        priority="high",
        next_action="Complete the next CRM action.",
        next_action_due_date=due_date,
        notes="Phase 6.4B fixture.",
        request_key="phase-6-4b-" + company.casefold().replace(" ", "-"),
        created_by_user_id=creator_id,
        assigned_to_user_id=assignee_id,
        business_development_owner_user_id=business_owner_id,
    ).lead
    if pipeline_status != "new":
        db.execute(
            """
            UPDATE leads
            SET pipeline_status = ?
            WHERE id = ?
            """,
            (pipeline_status, int(lead["id"])),
        )
    return dict(
        db.execute(
            "SELECT * FROM leads WHERE id = ?",
            (int(lead["id"]),),
        ).fetchone()
    )


@pytest.fixture
def route_context(tmp_path, monkeypatch):
    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / "phase-6-4b.db",
    )
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db)
        owner = dict(
            db.execute(
                """
                SELECT id, username, display_name, role, active
                FROM users
                WHERE id = ?
                """,
                (owner_id,),
            ).fetchone()
        )
        researcher = dict(
            create_lead_sourcer(
                db,
                username="queue-researcher",
                display_name="Queue Researcher",
                password="temporary-pass-123",
                password_confirmation="temporary-pass-123",
            )
        )
        other_researcher = dict(
            create_lead_sourcer(
                db,
                username="other-queue-researcher",
                display_name="Other Queue Researcher",
                password="temporary-pass-456",
                password_confirmation="temporary-pass-456",
            )
        )
        manager = dict(
            create_relationship_manager(
                db,
                username="queue-manager",
                display_name="Queue Manager",
                password="temporary-pass-789",
                password_confirmation="temporary-pass-789",
            )
        )
        other_manager = dict(
            create_relationship_manager(
                db,
                username="other-queue-manager",
                display_name="Other Queue Manager",
                password="temporary-pass-999",
                password_confirmation="temporary-pass-999",
            )
        )

        owner_lead = _lead(
            db,
            company="<script>Owner Due Today</script>",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            business_owner_id=manager["id"],
            due_date="2026-08-06",
        )
        researcher_lead = _lead(
            db,
            company="Researcher Due Today",
            creator_id=researcher["id"],
            assignee_id=researcher["id"],
            business_owner_id=manager["id"],
            due_date="2026-08-06",
        )
        hidden_lead = _lead(
            db,
            company="Hidden Other Team Lead",
            creator_id=other_researcher["id"],
            assignee_id=other_researcher["id"],
            business_owner_id=other_manager["id"],
            due_date="2026-08-06",
        )
        waiting_lead = _lead(
            db,
            company="Waiting for Reply Lead",
            creator_id=manager["id"],
            assignee_id=owner["id"],
            business_owner_id=manager["id"],
            pipeline_status="contacted",
        )
        create_activity(
            db,
            waiting_lead["id"],
            actor=owner,
            activity_type="email_sent",
            activity_at="2026-08-05T09:00:00+08:00",
            channel="email",
            message_summary="Sent the approved introduction.",
            notes="",
            performed_by_user_id=owner["id"],
            responsible_user_id=manager["id"],
            response_status="awaiting_reply",
            next_follow_up_date="2026-08-07",
        )

    original_builder = client_hunting.build_follow_up_command_center

    def fixed_builder(db, actor, **filters):
        return original_builder(
            db,
            actor,
            today=TODAY,
            **filters,
        )

    monkeypatch.setattr(
        client_hunting,
        "build_follow_up_command_center",
        fixed_builder,
    )

    return {
        "owner": owner,
        "researcher": researcher,
        "other_researcher": other_researcher,
        "manager": manager,
        "other_manager": other_manager,
        "owner_lead_id": int(owner_lead["id"]),
        "researcher_lead_id": int(researcher_lead["id"]),
        "hidden_lead_id": int(hidden_lead["id"]),
        "waiting_lead_id": int(waiting_lead["id"]),
    }


def test_owner_page_renders_all_queues_filters_and_safe_empty_states(
    route_context,
):
    context = route_context
    page = client_hunting.follow_up_command_center_page(
        _request(context["owner"]),
    )
    body = page.body.decode("utf-8")

    assert page.status_code == 200
    assert "Follow-up Command Center" in body
    for title in (
        "Due Today",
        "Overdue",
        "Due This Week",
        "Waiting for Reply",
        "No Contact for Five Days",
        "Approved but Not Contacted",
        "Research Awaiting Review",
        "Changes Requested",
        "Interested — Handoff to Mark",
        "Proposal Follow-up Required",
    ):
        assert title in body

    assert 'name="assignee_id"' in body
    assert 'name="researcher_id"' in body
    assert 'name="business_development_owner_id"' in body
    assert "Nothing is due today." not in body
    assert "No follow-up work is overdue." in body
    assert 'data-empty-queue="overdue"' in body

    assert "<script>Owner Due Today</script>" not in body
    assert "&lt;script&gt;Owner Due Today&lt;/script&gt;" in body
    assert "Waiting for Reply Lead" in body
    assert f'/crm/leads/{context["owner_lead_id"]}' in body


def test_assignee_filter_renders_only_matching_visible_leads(
    route_context,
):
    context = route_context
    page = client_hunting.follow_up_command_center_page(
        _request(
            context["owner"],
            query_string=f"assignee_id={context['owner']['id']}",
        ),
        assignee_id=context["owner"]["id"],
    )
    body = page.body.decode("utf-8")

    assert "&lt;script&gt;Owner Due Today&lt;/script&gt;" in body
    assert "Waiting for Reply Lead" in body
    assert "Researcher Due Today" not in body
    assert "Clear Filters" in body
    selected_owner = re.search(
        rf'<option\s+value="{context["owner"]["id"]}"\s+selected\s*>',
        body,
    )
    assert selected_owner is not None


def test_staff_page_never_renders_foreign_team_leads(
    route_context,
):
    context = route_context

    researcher_page = client_hunting.follow_up_command_center_page(
        _request(context["researcher"]),
    )
    researcher_body = researcher_page.body.decode("utf-8")
    assert "Researcher Due Today" in researcher_body
    assert "Hidden Other Team Lead" not in researcher_body
    assert "Waiting for Reply Lead" not in researcher_body

    manager_page = client_hunting.follow_up_command_center_page(
        _request(context["manager"]),
    )
    manager_body = manager_page.body.decode("utf-8")
    assert "&lt;script&gt;Owner Due Today&lt;/script&gt;" in manager_body
    assert "Researcher Due Today" in manager_body
    assert "Waiting for Reply Lead" in manager_body
    assert "Hidden Other Team Lead" not in manager_body


def test_follow_up_route_access_and_invalid_filter_fail_closed(
    route_context,
):
    context = route_context
    path = "/crm/follow-ups"

    for user in (
        context["owner"],
        context["researcher"],
        context["manager"],
    ):
        assert can_access_request(user, "GET", path)
        assert can_access_request(user, "HEAD", path)

    member = {
        "id": 100,
        "username": "member",
        "display_name": "Member",
        "role": "member",
    }
    assert not can_access_request(member, "GET", path)

    with pytest.raises(HTTPException) as error:
        client_hunting.follow_up_command_center_page(
            _request(context["owner"]),
            assignee_id=0,
        )
    assert error.value.status_code == 400
