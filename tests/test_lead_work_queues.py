from __future__ import annotations

from pathlib import Path

import pytest

from app import database
from app.services.lead_work_queues import (
    build_role_aware_crm_dashboard,
)
from app.services.leads import create_lead
from app.services.passwords import hash_password
from app.services.team_users import (
    create_lead_sourcer,
    get_primary_owner_id,
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv(
        "MARK_OS_USERNAME",
        "mark",
    )
    monkeypatch.setenv(
        "MARK_OS_PASSWORD",
        "owner-password-123",
    )
    monkeypatch.setenv(
        "MARK_OS_DISPLAY_NAME",
        "Mark",
    )


@pytest.fixture
def queue_database(tmp_path, monkeypatch):
    path = tmp_path / "phase-6-1g.db"
    monkeypatch.setattr(
        database,
        "DB_PATH",
        path,
    )
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db)
        brother = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="temporary-pass-123",
            password_confirmation=(
                "temporary-pass-123"
            ),
        )
        other = create_lead_sourcer(
            db,
            username="other-researcher",
            display_name="Other Researcher",
            password="temporary-pass-456",
            password_confirmation=(
                "temporary-pass-456"
            ),
        )
        member_id = db.execute(
            """
            INSERT INTO users (
                username,
                display_name,
                password_hash,
                role,
                active,
                must_change_password
            )
            VALUES (
                'member',
                'Member',
                ?,
                'member',
                1,
                0
            )
            """,
            (
                hash_password(
                    "member-password-123"
                ),
            ),
        ).lastrowid

    return {
        "path": path,
        "owner": {
            "id": owner_id,
            "username": "mark",
            "role": "owner",
        },
        "brother": dict(brother),
        "other": dict(other),
        "member": {
            "id": member_id,
            "username": "member",
            "role": "member",
        },
    }


def _create(
    db,
    *,
    company: str,
    created_by: int,
    assigned_to: int,
):
    return create_lead(
        db,
        company=company,
        contact_person=f"{company} Contact",
        job_title="Founder",
        source="LinkedIn",
        source_url=(
            "https://example.com/"
            + company.casefold().replace(" ", "-")
        ),
        problem_opportunity=(
            "Reporting is still manual."
        ),
        why_mark_fits=(
            "Mark can automate the workflow."
        ),
        pipeline_status="new",
        priority="medium",
        next_action="Complete the next CRM step.",
        next_action_due_date="2026-08-20",
        notes="Queue fixture.",
        created_by_user_id=created_by,
        assigned_to_user_id=assigned_to,
    ).lead


def _set_state(
    db,
    lead_id: int,
    *,
    research_status: str,
    pipeline_status: str = "new",
    researched_by_user_id: int | None = None,
    outreach_approved_by_user_id: int | None = None,
    outreach_approved_at: str | None = None,
    review_notes: str = "",
    deleted_at: str | None = None,
):
    db.execute(
        """
        UPDATE leads
        SET
            research_status = ?,
            pipeline_status = ?,
            researched_by_user_id = ?,
            outreach_approved_by_user_id = ?,
            outreach_approved_at = ?,
            review_notes = ?,
            deleted_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            research_status,
            pipeline_status,
            researched_by_user_id,
            outreach_approved_by_user_id,
            outreach_approved_at,
            review_notes,
            deleted_at,
            lead_id,
        ),
    )


def _queues_by_key(context):
    return {
        queue["key"]: queue
        for queue in context["queue_cards"]
    }


def test_owner_receives_three_decision_queues(
    queue_database,
):
    owner = queue_database["owner"]

    with database.get_db() as db:
        waiting = _create(
            db,
            company="Waiting Review",
            created_by=owner["id"],
            assigned_to=owner["id"],
        )
        approval = _create(
            db,
            company="Needs Outreach Approval",
            created_by=owner["id"],
            assigned_to=owner["id"],
        )
        ready = _create(
            db,
            company="Ready Contact",
            created_by=owner["id"],
            assigned_to=owner["id"],
        )
        won = _create(
            db,
            company="Already Won",
            created_by=owner["id"],
            assigned_to=owner["id"],
        )
        deleted = _create(
            db,
            company="Deleted Review",
            created_by=owner["id"],
            assigned_to=owner["id"],
        )

        _set_state(
            db,
            waiting["id"],
            research_status="ready_for_review",
        )
        _set_state(
            db,
            approval["id"],
            research_status="approved",
        )
        _set_state(
            db,
            ready["id"],
            research_status="approved",
            outreach_approved_by_user_id=(
                owner["id"]
            ),
            outreach_approved_at=(
                "2026-08-05 12:00:00"
            ),
        )
        _set_state(
            db,
            won["id"],
            research_status="approved",
            pipeline_status="won",
        )
        _set_state(
            db,
            deleted["id"],
            research_status="ready_for_review",
            deleted_at="2026-08-05 13:00:00",
        )

        context = build_role_aware_crm_dashboard(
            db,
            owner,
        )

    queues = _queues_by_key(context)
    assert context["queue_mode"] == "owner"
    assert context["metric_cards"] is None
    assert set(queues) == {
        "owner_review",
        "owner_outreach",
        "owner_ready_contact",
    }
    assert queues["owner_review"]["count"] == 1
    assert [
        lead["id"]
        for lead in queues["owner_review"]["leads"]
    ] == [waiting["id"]]
    assert queues["owner_outreach"]["count"] == 1
    assert [
        lead["id"]
        for lead in queues["owner_outreach"]["leads"]
    ] == [approval["id"]]
    assert (
        queues["owner_ready_contact"]["count"]
        == 1
    )
    assert [
        lead["id"]
        for lead
        in queues["owner_ready_contact"]["leads"]
    ] == [ready["id"]]

    visible_ids = {
        lead["id"]
        for lead in context["leads"]
    }
    assert waiting["id"] in visible_ids
    assert approval["id"] in visible_ids
    assert ready["id"] in visible_ids
    assert won["id"] in visible_ids
    assert deleted["id"] not in visible_ids


def test_researcher_queues_use_all_permitted_relationships(
    queue_database,
):
    owner = queue_database["owner"]
    brother = queue_database["brother"]
    other = queue_database["other"]

    with database.get_db() as db:
        own_active = _create(
            db,
            company="Own Active",
            created_by=brother["id"],
            assigned_to=owner["id"],
        )
        assigned_changes = _create(
            db,
            company="Assigned Changes",
            created_by=owner["id"],
            assigned_to=brother["id"],
        )
        researched_waiting = _create(
            db,
            company="Researched Waiting",
            created_by=owner["id"],
            assigned_to=owner["id"],
        )
        own_approved = _create(
            db,
            company="Own Approved",
            created_by=brother["id"],
            assigned_to=owner["id"],
        )
        unrelated = _create(
            db,
            company="Other Researcher Lead",
            created_by=other["id"],
            assigned_to=owner["id"],
        )

        _set_state(
            db,
            own_active["id"],
            research_status="researching",
            researched_by_user_id=brother["id"],
        )
        _set_state(
            db,
            assigned_changes["id"],
            research_status="changes_requested",
            researched_by_user_id=other["id"],
            review_notes="Verify the source link.",
        )
        _set_state(
            db,
            researched_waiting["id"],
            research_status="ready_for_review",
            researched_by_user_id=brother["id"],
        )
        _set_state(
            db,
            own_approved["id"],
            research_status="approved",
            researched_by_user_id=brother["id"],
        )
        _set_state(
            db,
            unrelated["id"],
            research_status="researching",
            researched_by_user_id=other["id"],
        )

        context = build_role_aware_crm_dashboard(
            db,
            brother,
        )

    queues = _queues_by_key(context)
    assert context["queue_mode"] == "researcher"
    assert set(queues) == {
        "research_changes",
        "research_active",
        "research_waiting",
        "research_decided",
    }

    visible_ids = {
        lead["id"]
        for lead in context["leads"]
    }
    assert visible_ids == {
        own_active["id"],
        assigned_changes["id"],
        researched_waiting["id"],
        own_approved["id"],
    }
    assert unrelated["id"] not in visible_ids

    assert [
        lead["id"]
        for lead
        in queues["research_changes"]["leads"]
    ] == [assigned_changes["id"]]
    assert [
        lead["id"]
        for lead
        in queues["research_active"]["leads"]
    ] == [own_active["id"]]
    assert [
        lead["id"]
        for lead
        in queues["research_waiting"]["leads"]
    ] == [researched_waiting["id"]]
    assert [
        lead["id"]
        for lead
        in queues["research_decided"]["leads"]
    ] == [own_approved["id"]]

    metrics = {
        card["label"]: card["value"]
        for card in context["metric_cards"]
    }
    assert metrics == {
        "Needs changes": 1,
        "In research": 1,
        "Waiting review": 1,
        "Approved": 1,
    }
    assert (
        queues["research_changes"]["leads"][0][
            "queue_action_url"
        ]
        == (
            f"/crm/leads/{assigned_changes['id']}"
            "/research/edit"
        )
    )


def test_member_receives_no_crm_queue_data(
    queue_database,
):
    with database.get_db() as db:
        context = build_role_aware_crm_dashboard(
            db,
            queue_database["member"],
        )

    assert context == {
        "queue_mode": "none",
        "queue_cards": [],
        "metric_cards": [],
        "leads": [],
    }


def test_role_aware_queue_templates_are_present():
    project_root = (
        Path(__file__).resolve().parent.parent
    )
    dashboard = (
        project_root
        / "app/templates/client_hunting.html"
    ).read_text(encoding="utf-8")
    queues = (
        project_root
        / "app/templates/partials/"
        "crm_role_queues.html"
    ).read_text(encoding="utf-8")
    route = (
        project_root
        / "app/routes/client_hunting.py"
    ).read_text(encoding="utf-8")

    assert (
        '{% include "partials/'
        'crm_role_queues.html" %}'
        in dashboard
    )
    assert "Lead Researcher access" in dashboard
    assert (
        "{% if can_manage_crm %}<th>Quest</th>"
        "{% endif %}"
        in dashboard
    )
    assert "Owner Decision Queues" in queues
    assert "Lead Researcher Workspace" in queues
    assert "queue_action_url" in queues
    assert "can_view_lead" in route
    assert (
        "build_role_aware_crm_dashboard"
        in route
    )
