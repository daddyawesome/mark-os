from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from app import database
from app.routes import client_hunting
from app.services.access_control import can_access_request
from app.services.leads import create_lead
from app.services.team_users import (
    create_lead_sourcer,
    create_relationship_manager,
    get_primary_owner_id,
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _request(
    user: dict,
    path: str,
    *,
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


@pytest.fixture
def activity_route_context(tmp_path, monkeypatch):
    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / "phase-6-3c.db",
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
        sourcer = dict(
            create_lead_sourcer(
                db,
                username="researcher",
                display_name="Lead Researcher",
                password="temporary-pass-123",
                password_confirmation="temporary-pass-123",
            )
        )
        other_sourcer = dict(
            create_lead_sourcer(
                db,
                username="other-researcher",
                display_name="Other Researcher",
                password="temporary-pass-456",
                password_confirmation="temporary-pass-456",
            )
        )
        manager = dict(
            create_relationship_manager(
                db,
                username="junmar",
                display_name="Junmar",
                password="temporary-pass-789",
                password_confirmation="temporary-pass-789",
            )
        )

        lead = create_lead(
            db,
            company="Timeline Company",
            contact_person="Alex Buyer",
            job_title="Founder",
            source="LinkedIn",
            source_url="https://example.com/timeline",
            problem_opportunity="Follow-up context is fragmented.",
            why_mark_fits="Mark can build the operating workflow.",
            pipeline_status="new",
            priority="high",
            next_action="Complete account research.",
            next_action_due_date="2026-08-10",
            notes="Phase 6.3C fixture.",
            request_key="phase-6-3c-main",
            created_by_user_id=sourcer["id"],
            assigned_to_user_id=sourcer["id"],
            business_development_owner_user_id=manager["id"],
        ).lead

        other_lead = create_lead(
            db,
            company="Hidden Timeline Company",
            contact_person="Taylor Buyer",
            source="Referral",
            problem_opportunity="Ownership is unclear.",
            why_mark_fits="Mark can clarify ownership.",
            next_action="Research the account.",
            request_key="phase-6-3c-hidden",
            created_by_user_id=other_sourcer["id"],
            assigned_to_user_id=other_sourcer["id"],
        ).lead

    return {
        "owner": owner,
        "sourcer": sourcer,
        "other_sourcer": other_sourcer,
        "manager": manager,
        "lead_id": int(lead["id"]),
        "other_lead_id": int(other_lead["id"]),
    }


def test_owner_routes_render_chronological_timeline_and_escape_summary(
    activity_route_context,
):
    context = activity_route_context
    request = SimpleNamespace(
        state=SimpleNamespace(current_user=context["owner"])
    )

    first = client_hunting.create_lead_activity(
        request,
        context["lead_id"],
        activity_type="research_started",
        activity_at="2026-08-06T08:00",
        channel="internal",
        message_summary="Older timeline entry.",
        notes="",
        performed_by_user_id=str(context["owner"]["id"]),
        responsible_user_id="",
        response_status="not_applicable",
        next_follow_up_date="",
    )
    second = client_hunting.create_lead_activity(
        request,
        context["lead_id"],
        activity_type="email_sent",
        activity_at="2026-08-06T09:00",
        channel="email",
        message_summary="<script>Newest timeline entry.</script>",
        notes="Approved wording was used.",
        performed_by_user_id=str(context["owner"]["id"]),
        responsible_user_id=str(context["manager"]["id"]),
        response_status="awaiting_reply",
        next_follow_up_date="2026-08-09",
    )

    assert first.status_code == 303
    assert first.headers["location"].endswith(
        "?notice=activity_created#lead-activity-timeline"
    )
    assert second.status_code == 303

    page = client_hunting.lead_detail(
        _request(
            context["owner"],
            f"/crm/leads/{context['lead_id']}",
        ),
        context["lead_id"],
    )
    body = page.body.decode("utf-8")

    assert "Lead Activity Timeline" in body
    assert body.index("Older timeline entry.") < body.index(
        "Newest timeline entry."
    )
    assert "<script>Newest timeline entry.</script>" not in body
    assert "&lt;script&gt;Newest timeline entry.&lt;/script&gt;" in body
    assert "Junmar" in body
    assert "Save Activity" in body


def test_owner_correction_and_soft_delete_are_auditable(
    activity_route_context,
):
    context = activity_route_context
    request = SimpleNamespace(
        state=SimpleNamespace(current_user=context["owner"])
    )
    client_hunting.create_lead_activity(
        request,
        context["lead_id"],
        activity_type="email_sent",
        activity_at="2026-08-06T10:00",
        channel="email",
        message_summary="Original outreach summary.",
        notes="Original note.",
        performed_by_user_id=str(context["owner"]["id"]),
        responsible_user_id=str(context["manager"]["id"]),
        response_status="awaiting_reply",
        next_follow_up_date="2026-08-10",
    )

    with database.get_db() as db:
        activity = db.execute(
            """
            SELECT *
            FROM lead_activities
            WHERE lead_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (context["lead_id"],),
        ).fetchone()
        activity_id = int(activity["id"])
        original_author = int(activity["created_by_user_id"])

    corrected = client_hunting.correct_lead_activity(
        request,
        context["lead_id"],
        activity_id,
        correction_reason="Corrected the outreach summary.",
        activity_type="email_sent",
        activity_at="2026-08-06T10:00",
        channel="email",
        message_summary="Corrected outreach summary.",
        notes="Corrected note.",
        performed_by_user_id=str(context["owner"]["id"]),
        responsible_user_id=str(context["manager"]["id"]),
        response_status="awaiting_reply",
        next_follow_up_date="2026-08-11",
    )
    assert corrected.status_code == 303
    assert corrected.headers["location"].endswith(
        "?notice=activity_corrected#lead-activity-timeline"
    )

    with database.get_db() as db:
        row = db.execute(
            "SELECT * FROM lead_activities WHERE id = ?",
            (activity_id,),
        ).fetchone()
        assert row["created_by_user_id"] == original_author
        assert row["corrected_by_user_id"] == context["owner"]["id"]
        assert row["correction_reason"] == (
            "Corrected the outreach summary."
        )
        assert row["message_summary"] == "Corrected outreach summary."
        assert row["next_follow_up_date"] == "2026-08-11"

    deleted = client_hunting.delete_lead_activity(
        request,
        context["lead_id"],
        activity_id,
        correction_reason="Duplicate contact entry.",
    )
    assert deleted.status_code == 303

    hidden_page = client_hunting.lead_detail(
        _request(
            context["owner"],
            f"/crm/leads/{context['lead_id']}",
        ),
        context["lead_id"],
    )
    assert "Corrected outreach summary." not in hidden_page.body.decode(
        "utf-8"
    )

    audit_page = client_hunting.lead_detail(
        _request(
            context["owner"],
            f"/crm/leads/{context['lead_id']}",
            query_string="include_deleted=1",
        ),
        context["lead_id"],
    )
    audit_body = audit_page.body.decode("utf-8")
    assert "Corrected outreach summary." in audit_body
    assert "Duplicate contact entry." in audit_body
    assert "Deleted" in audit_body


def test_sourcer_can_record_and_correct_own_internal_research_only(
    activity_route_context,
):
    context = activity_route_context
    request = SimpleNamespace(
        state=SimpleNamespace(current_user=context["sourcer"])
    )
    created = client_hunting.create_lead_activity(
        request,
        context["lead_id"],
        activity_type="research_started",
        activity_at="2026-08-06T11:00",
        channel="internal",
        message_summary="Started deterministic research.",
        notes="",
        performed_by_user_id="",
        responsible_user_id="",
        response_status="not_applicable",
        next_follow_up_date="",
    )
    assert created.status_code == 303

    with database.get_db() as db:
        activity = db.execute(
            """
            SELECT *
            FROM lead_activities
            WHERE lead_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (context["lead_id"],),
        ).fetchone()
        activity_id = int(activity["id"])
        assert activity["created_by_user_id"] == context["sourcer"]["id"]
        assert activity["performed_by_user_id"] == context["sourcer"]["id"]

    corrected = client_hunting.correct_lead_activity(
        request,
        context["lead_id"],
        activity_id,
        correction_reason="Corrected the research wording.",
        activity_type="research_started",
        activity_at="2026-08-06T11:00",
        channel="internal",
        message_summary="Started account research.",
        notes="",
        performed_by_user_id="",
        responsible_user_id="",
        response_status="not_applicable",
        next_follow_up_date="",
    )
    assert corrected.status_code == 303

    denied = client_hunting.create_lead_activity(
        request,
        context["lead_id"],
        activity_type="email_sent",
        activity_at="2026-08-06T12:00",
        channel="email",
        message_summary="Unauthorized outreach attempt.",
        notes="",
        performed_by_user_id="",
        responsible_user_id="",
        response_status="awaiting_reply",
        next_follow_up_date="",
    )
    assert denied.status_code == 303
    assert denied.headers["location"].endswith(
        "?error=activity_forbidden#lead-activity-timeline"
    )

    with database.get_db() as db:
        assert db.execute(
            """
            SELECT COUNT(*)
            FROM lead_activities
            WHERE message_summary = 'Unauthorized outreach attempt.'
            """
        ).fetchone()[0] == 0


def test_relationship_manager_timeline_is_read_only_even_for_direct_call(
    activity_route_context,
):
    context = activity_route_context
    owner_request = SimpleNamespace(
        state=SimpleNamespace(current_user=context["owner"])
    )
    client_hunting.create_lead_activity(
        owner_request,
        context["lead_id"],
        activity_type="approved_for_outreach",
        activity_at="2026-08-06T13:00",
        channel="internal",
        message_summary="Visible relationship timeline event.",
        notes="",
        performed_by_user_id=str(context["owner"]["id"]),
        responsible_user_id=str(context["manager"]["id"]),
        response_status="not_applicable",
        next_follow_up_date="",
    )

    page = client_hunting.lead_detail(
        _request(
            context["manager"],
            f"/crm/leads/{context['lead_id']}",
        ),
        context["lead_id"],
    )
    body = page.body.decode("utf-8")
    assert "Visible relationship timeline event." in body
    assert "This timeline is read-only." in body
    assert "Save Activity" not in body
    assert "Correct this activity" not in body

    manager_request = SimpleNamespace(
        state=SimpleNamespace(current_user=context["manager"])
    )
    denied = client_hunting.create_lead_activity(
        manager_request,
        context["lead_id"],
        activity_type="email_sent",
        activity_at="2026-08-06T14:00",
        channel="email",
        message_summary="Forged manager outreach.",
        notes="",
        performed_by_user_id="",
        responsible_user_id="",
        response_status="awaiting_reply",
        next_follow_up_date="",
    )
    assert denied.status_code == 303
    assert "activity_forbidden" in denied.headers["location"]


def test_cross_user_activity_routes_use_not_found(
    activity_route_context,
):
    context = activity_route_context
    other_request = SimpleNamespace(
        state=SimpleNamespace(
            current_user=context["other_sourcer"]
        )
    )

    with pytest.raises(HTTPException) as detail_error:
        client_hunting.lead_detail(
            _request(
                context["other_sourcer"],
                f"/crm/leads/{context['lead_id']}",
            ),
            context["lead_id"],
        )
    assert detail_error.value.status_code == 404

    with pytest.raises(HTTPException) as create_error:
        client_hunting.create_lead_activity(
            other_request,
            context["lead_id"],
            activity_type="research_started",
            activity_at="2026-08-06T15:00",
            channel="internal",
            message_summary="Cross-user attempt.",
            notes="",
            performed_by_user_id="",
            responsible_user_id="",
            response_status="not_applicable",
            next_follow_up_date="",
        )
    assert create_error.value.status_code == 404


def test_activity_route_middleware_surface_stays_narrow(
    activity_route_context,
):
    context = activity_route_context
    create_path = f"/crm/leads/{context['lead_id']}/activities"
    correct_path = (
        f"/crm/leads/{context['lead_id']}/activities/1/correct"
    )
    delete_path = (
        f"/crm/leads/{context['lead_id']}/activities/1/delete"
    )

    for path in (create_path, correct_path, delete_path):
        assert can_access_request(context["owner"], "POST", path)
        assert can_access_request(context["sourcer"], "POST", path)

    # Phase 6.13: creating an activity is route-reachable for any
    # Relationship Manager — the delegated-contact permission
    # (can_perform_delegated_contact) is the real, service-layer boundary.
    # Correcting/deleting an activity stays workspace-owner-authority only;
    # that is a materially more sensitive action this phase does not touch.
    assert can_access_request(context["manager"], "POST", create_path)
    for path in (correct_path, delete_path):
        assert not can_access_request(
            context["manager"],
            "POST",
            path,
        )

    member = {
        "id": 99,
        "username": "member",
        "display_name": "Member",
        "role": "member",
    }
    assert not can_access_request(member, "POST", create_path)
