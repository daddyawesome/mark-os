from __future__ import annotations

import pytest

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.lead_activities import create_activity
from app.services.lead_research_workflow import (
    review_research,
    submit_research_for_review,
    update_research_details,
)
from app.services.lead_sourcing_effort import (
    EffortPermissionError,
    compute_lead_sourcing_effort,
)
from app.services.leads import create_lead
from app.services.team_users import create_lead_sourcer


OWNER = {"id": 1, "username": "mark", "role": "owner"}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def effort_database(tmp_path, monkeypatch):
    path = tmp_path / "lead-sourcing-effort.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        sourcer = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )

    return {"path": path, "organization_id": organization_id, "sourcer": dict(sourcer)}


def _create_lead(db, *, organization_id, company, sourcer_id):
    return create_lead(
        db,
        company=company,
        contact_person="Dana Buyer",
        job_title="Founder",
        source="LinkedIn",
        source_url="https://example.com/" + company.casefold().replace(" ", "-"),
        problem_opportunity="Reporting is manual.",
        why_mark_fits="Mark can automate reporting.",
        pipeline_status="new",
        priority="medium",
        next_action="Complete research.",
        next_action_due_date="2026-08-10",
        notes="",
        created_by_user_id=sourcer_id,
        assigned_to_user_id=sourcer_id,
        organization_id=organization_id,
    ).lead


def _research_and_submit(db, lead, sourcer_actor):
    update_research_details(
        db,
        lead["id"],
        actor=sourcer_actor,
        company=lead["company"],
        contact_person=lead["contact_person"],
        source=lead["source"],
        problem_opportunity="Verified manual weekly reporting.",
        why_mark_fits="Mark has relevant Power BI work.",
        next_action="Mark reviews the lead research.",
    )
    return submit_research_for_review(db, lead["id"], actor=sourcer_actor)


def test_effort_summary_derives_from_existing_records(effort_database):
    organization_id = effort_database["organization_id"]
    sourcer = effort_database["sourcer"]
    sourcer_actor = {"id": sourcer["id"], "role": "lead_sourcer"}

    with database.get_db() as db:
        approved_lead = _create_lead(
            db,
            organization_id=organization_id,
            company="Approved Co",
            sourcer_id=sourcer["id"],
        )
        submitted = _research_and_submit(db, approved_lead, sourcer_actor)
        review_research(
            db,
            approved_lead["id"],
            actor=OWNER,
            decision="approved",
        )

        bounced_lead = _create_lead(
            db,
            organization_id=organization_id,
            company="Bounced Co",
            sourcer_id=sourcer["id"],
        )
        _research_and_submit(db, bounced_lead, sourcer_actor)
        review_research(
            db,
            bounced_lead["id"],
            actor=OWNER,
            decision="changes_requested",
            review_notes="Verify the contact title.",
        )

        create_activity(
            db,
            lead_id=approved_lead["id"],
            actor=OWNER,
            activity_type="linkedin_message_sent",
            activity_at="2026-08-05T10:00:00",
            channel="linkedin",
            message_summary="Sent a warm introduction.",
            performed_by_user_id=sourcer["id"],
        )

        summary = compute_lead_sourcing_effort(
            db,
            actor=sourcer_actor,
            user_id=sourcer["id"],
            organization_id=organization_id,
            period_start="2000-01-01",
            period_end="2100-01-01",
        )

    assert summary.leads_researched == 2
    assert summary.leads_submitted == 2
    assert summary.approved_count == 1
    assert summary.changes_requested_count == 1
    assert summary.approval_rate == pytest.approx(0.5)
    assert summary.relationship_actions == 1
    assert summary.research_minutes is None


def test_effort_summary_outside_period_is_excluded(effort_database):
    organization_id = effort_database["organization_id"]
    sourcer = effort_database["sourcer"]
    sourcer_actor = {"id": sourcer["id"], "role": "lead_sourcer"}

    with database.get_db() as db:
        lead = _create_lead(
            db,
            organization_id=organization_id,
            company="Out Of Range Co",
            sourcer_id=sourcer["id"],
        )
        _research_and_submit(db, lead, sourcer_actor)

        summary = compute_lead_sourcing_effort(
            db,
            actor=sourcer_actor,
            user_id=sourcer["id"],
            organization_id=organization_id,
            period_start="1999-01-01",
            period_end="1999-12-31",
        )

    assert summary.leads_researched == 0
    assert summary.leads_submitted == 0
    assert summary.approval_rate is None


def test_user_can_view_own_effort_without_owner_authority(effort_database):
    organization_id = effort_database["organization_id"]
    sourcer = effort_database["sourcer"]
    sourcer_actor = {"id": sourcer["id"], "role": "lead_sourcer"}

    with database.get_db() as db:
        summary = compute_lead_sourcing_effort(
            db,
            actor=sourcer_actor,
            user_id=sourcer["id"],
            organization_id=organization_id,
            period_start="2000-01-01",
            period_end="2100-01-01",
        )

    assert summary.user_id == sourcer["id"]


def test_sourcer_cannot_view_another_users_effort(effort_database):
    organization_id = effort_database["organization_id"]
    sourcer = effort_database["sourcer"]
    sourcer_actor = {"id": sourcer["id"], "role": "lead_sourcer"}

    with database.get_db() as db:
        with pytest.raises(EffortPermissionError):
            compute_lead_sourcing_effort(
                db,
                actor=sourcer_actor,
                user_id=OWNER["id"],
                organization_id=organization_id,
                period_start="2000-01-01",
                period_end="2100-01-01",
            )


def test_owner_can_view_any_users_effort(effort_database):
    organization_id = effort_database["organization_id"]
    sourcer = effort_database["sourcer"]

    with database.get_db() as db:
        summary = compute_lead_sourcing_effort(
            db,
            actor=OWNER,
            user_id=sourcer["id"],
            organization_id=organization_id,
            period_start="2000-01-01",
            period_end="2100-01-01",
        )

    assert summary.user_id == sourcer["id"]
