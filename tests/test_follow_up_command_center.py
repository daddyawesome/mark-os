from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app import database
from app.services.follow_up_command_center import (
    FollowUpFilterError,
    FollowUpPermissionError,
    build_follow_up_command_center,
    resolve_manila_today,
)
from app.services.lead_activities import (
    create_activity,
    soft_delete_activity,
)
from app.services.leads import create_lead


TODAY = date(2026, 8, 6)


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


def _insert_user(
    db,
    *,
    username: str,
    display_name: str,
    role: str,
    active: int = 1,
) -> dict:
    user_id = int(
        db.execute(
            """
            INSERT INTO users (
                username,
                display_name,
                password_hash,
                role,
                active
            )
            VALUES (?, ?, 'test-password-hash', ?, ?)
            """,
            (
                username,
                display_name,
                role,
                active,
            ),
        ).lastrowid
    )
    return {
        "id": user_id,
        "username": username,
        "display_name": display_name,
        "role": role,
        "active": active,
    }


def _owner(db) -> dict:
    return dict(
        db.execute(
            """
            SELECT
                id,
                username,
                display_name,
                role,
                active
            FROM users
            WHERE role = 'owner'
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
    )


def _lead(
    db,
    *,
    company: str,
    creator_id: int,
    assignee_id: int | None,
    researcher_id: int | None = None,
    business_owner_id: int | None = None,
    pipeline_status: str = "new",
    research_status: str = "draft",
    priority: str = "medium",
    due_date: str | None = None,
    submitted_at: str | None = None,
    reviewed_at: str | None = None,
    outreach_approved_by_user_id: int | None = None,
    outreach_approved_at: str | None = None,
) -> dict:
    created = create_lead(
        db,
        company=company,
        contact_person="Alex Buyer",
        job_title="Decision Maker",
        source="LinkedIn",
        source_url=(
            "https://example.com/"
            + company.casefold().replace(" ", "-")
        ),
        problem_opportunity=(
            "Follow-up work needs deterministic visibility."
        ),
        why_mark_fits=(
            "Mark can build and operate the workflow."
        ),
        pipeline_status="new",
        priority=priority,
        next_action="Complete the next CRM action.",
        next_action_due_date=due_date,
        notes="Phase 6.4A fixture.",
        request_key=(
            "phase-6-4a-"
            + company.casefold().replace(" ", "-")
        ),
        created_by_user_id=creator_id,
        assigned_to_user_id=assignee_id,
        business_development_owner_user_id=(
            business_owner_id
        ),
    ).lead

    db.execute(
        """
        UPDATE leads
        SET
            researched_by_user_id = ?,
            research_status = ?,
            submitted_for_review_at = ?,
            reviewed_at = ?,
            outreach_approved_by_user_id = ?,
            outreach_approved_at = ?,
            pipeline_status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            researcher_id,
            research_status,
            submitted_at,
            reviewed_at,
            outreach_approved_by_user_id,
            outreach_approved_at,
            pipeline_status,
            int(created["id"]),
        ),
    )
    return dict(
        db.execute(
            "SELECT * FROM leads WHERE id = ?",
            (int(created["id"]),),
        ).fetchone()
    )


def _activity(
    db,
    *,
    owner: dict,
    lead_id: int,
    activity_at: str,
    response_status: str,
    next_follow_up_date: str | None,
    responsible_user_id: int | None,
    channel: str = "email",
    summary: str = "Recorded external activity.",
):
    return create_activity(
        db,
        lead_id,
        actor=owner,
        activity_type="email_sent",
        activity_at=activity_at,
        channel=channel,
        message_summary=summary,
        notes="",
        performed_by_user_id=owner["id"],
        responsible_user_id=responsible_user_id,
        response_status=response_status,
        next_follow_up_date=next_follow_up_date,
    )


@pytest.fixture
def command_center_context(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / "phase-6-4a.db",
    )
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner = _owner(db)
        researcher = _insert_user(
            db,
            username="researcher",
            display_name="Lead Researcher",
            role="lead_sourcer",
        )
        other_researcher = _insert_user(
            db,
            username="other-researcher",
            display_name="Other Researcher",
            role="lead_sourcer",
        )
        manager = _insert_user(
            db,
            username="relationship-manager",
            display_name="Relationship Manager",
            role="relationship_manager",
        )
        other_manager = _insert_user(
            db,
            username="other-manager",
            display_name="Other Manager",
            role="relationship_manager",
        )
        member = _insert_user(
            db,
            username="member",
            display_name="Member",
            role="member",
        )
        inactive = _insert_user(
            db,
            username="inactive",
            display_name="Inactive Researcher",
            role="lead_sourcer",
            active=0,
        )

    return {
        "owner": owner,
        "researcher": researcher,
        "other_researcher": other_researcher,
        "manager": manager,
        "other_manager": other_manager,
        "member": member,
        "inactive": inactive,
    }


def test_manila_operational_date_changes_at_local_midnight():
    before_midnight = resolve_manila_today(
        datetime(
            2026,
            8,
            5,
            15,
            59,
            59,
            tzinfo=timezone.utc,
        )
    )
    at_midnight = resolve_manila_today(
        datetime(
            2026,
            8,
            5,
            16,
            0,
            0,
            tzinfo=timezone.utc,
        )
    )

    assert before_midnight == date(2026, 8, 5)
    assert at_midnight == date(2026, 8, 6)

    with pytest.raises(
        ValueError,
        match="timezone",
    ):
        resolve_manila_today(
            datetime(2026, 8, 6, 8, 0, 0)
        )


def test_owner_receives_all_required_queues_with_deterministic_order(
    command_center_context,
):
    context = command_center_context
    owner = context["owner"]
    researcher = context["researcher"]
    manager = context["manager"]

    with database.get_db() as db:
        older_overdue = _lead(
            db,
            company="Older Overdue",
            creator_id=researcher["id"],
            assignee_id=researcher["id"],
            researcher_id=researcher["id"],
            business_owner_id=manager["id"],
            due_date="2026-08-20",
            priority="low",
        )
        _activity(
            db,
            owner=owner,
            lead_id=older_overdue["id"],
            activity_at="2026-08-01T08:00:00+08:00",
            response_status="awaiting_reply",
            next_follow_up_date="2026-08-01",
            responsible_user_id=manager["id"],
        )

        newer_overdue = _lead(
            db,
            company="Newer Overdue",
            creator_id=researcher["id"],
            assignee_id=researcher["id"],
            researcher_id=researcher["id"],
            due_date="2026-08-05",
            priority="high",
        )
        due_today = _lead(
            db,
            company="Due Today",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            researcher_id=researcher["id"],
            due_date="2026-08-06",
        )
        due_week = _lead(
            db,
            company="Due This Week",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            researcher_id=researcher["id"],
            due_date="2026-08-09",
        )
        stale = _lead(
            db,
            company="Stale Contact",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            researcher_id=researcher["id"],
            pipeline_status="contacted",
        )
        _activity(
            db,
            owner=owner,
            lead_id=stale["id"],
            activity_at="2026-08-01T09:00:00+08:00",
            response_status="replied",
            next_follow_up_date=None,
            responsible_user_id=None,
        )

        approved = _lead(
            db,
            company="Approved Not Contacted",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            researcher_id=researcher["id"],
            business_owner_id=manager["id"],
            research_status="approved",
            outreach_approved_by_user_id=owner["id"],
            outreach_approved_at="2026-08-04 00:00:00",
        )
        awaiting_review = _lead(
            db,
            company="Awaiting Review",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            researcher_id=researcher["id"],
            research_status="ready_for_review",
            submitted_at="2026-08-03 00:00:00",
        )
        changes = _lead(
            db,
            company="Changes Requested",
            creator_id=researcher["id"],
            assignee_id=researcher["id"],
            researcher_id=researcher["id"],
            research_status="changes_requested",
            reviewed_at="2026-08-02 00:00:00",
        )
        interested = _lead(
            db,
            company="Interested Handoff",
            creator_id=manager["id"],
            assignee_id=owner["id"],
            business_owner_id=manager["id"],
            pipeline_status="replied",
        )
        _activity(
            db,
            owner=owner,
            lead_id=interested["id"],
            activity_at="2026-08-06T10:00:00+08:00",
            response_status="interested",
            next_follow_up_date="2026-08-08",
            responsible_user_id=owner["id"],
        )
        proposal = _lead(
            db,
            company="Proposal Missing Follow-up",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            researcher_id=researcher["id"],
            pipeline_status="proposal",
        )

        command_center = build_follow_up_command_center(
            db,
            owner,
            today=TODAY,
        )
        queues = command_center["queue_by_key"]

        assert command_center["timezone"] == "Asia/Manila"
        assert command_center["week_ends_on"] == "2026-08-09"
        assert [queue["key"] for queue in command_center["queues"]] == [
            "due_today",
            "overdue",
            "due_this_week",
            "waiting_for_reply",
            "no_contact_five_days",
            "approved_not_contacted",
            "research_awaiting_review",
            "changes_requested",
            "interested_handoff",
            "proposal_follow_up",
        ]

        assert [lead["company"] for lead in queues["overdue"]["leads"]] == [
            "Older Overdue",
            "Newer Overdue",
        ]
        assert queues["due_today"]["leads"][0]["id"] == due_today["id"]
        assert [
            lead["id"]
            for lead in queues["due_this_week"]["leads"]
        ] == [
            interested["id"],
            due_week["id"],
        ]
        assert queues["waiting_for_reply"]["leads"][0]["id"] == (
            older_overdue["id"]
        )
        assert [
            lead["id"]
            for lead in queues["no_contact_five_days"]["leads"]
        ] == [
            proposal["id"],
            stale["id"],
        ]
        assert queues["approved_not_contacted"]["leads"][0]["id"] == (
            approved["id"]
        )
        assert queues["research_awaiting_review"]["leads"][0]["id"] == (
            awaiting_review["id"]
        )
        assert queues["changes_requested"]["leads"][0]["id"] == (
            changes["id"]
        )
        assert queues["interested_handoff"]["leads"][0]["id"] == (
            interested["id"]
        )
        assert queues["proposal_follow_up"]["leads"][0]["id"] == (
            proposal["id"]
        )

        older_item = queues["overdue"]["leads"][0]
        assert older_item["effective_due_date"] == "2026-08-01"
        assert older_item["due_source"] == "activity"
        assert older_item["next_action_due_date"] == "2026-08-20"


def test_deleted_activity_is_ignored_for_due_and_response_state(
    command_center_context,
):
    context = command_center_context
    owner = context["owner"]
    researcher = context["researcher"]
    manager = context["manager"]

    with database.get_db() as db:
        lead = _lead(
            db,
            company="Deleted Activity",
            creator_id=researcher["id"],
            assignee_id=researcher["id"],
            researcher_id=researcher["id"],
            due_date="2026-08-10",
        )
        active_activity = _activity(
            db,
            owner=owner,
            lead_id=lead["id"],
            activity_at="2026-08-05T08:00:00+08:00",
            response_status="awaiting_reply",
            next_follow_up_date="2026-08-06",
            responsible_user_id=manager["id"],
        )
        deleted_activity = _activity(
            db,
            owner=owner,
            lead_id=lead["id"],
            activity_at="2026-08-06T08:00:00+08:00",
            response_status="interested",
            next_follow_up_date="2026-08-01",
            responsible_user_id=owner["id"],
        )
        soft_delete_activity(
            db,
            int(deleted_activity["id"]),
            actor=owner,
            correction_reason="Duplicate test activity.",
        )

        center = build_follow_up_command_center(
            db,
            owner,
            today=TODAY,
        )
        queues = center["queue_by_key"]

        assert queues["due_today"]["count"] == 1
        assert queues["overdue"]["count"] == 0
        assert queues["waiting_for_reply"]["count"] == 1
        assert queues["interested_handoff"]["count"] == 0

        item = queues["due_today"]["leads"][0]
        assert item["id"] == lead["id"]
        assert item["last_contact_at"] == active_activity["activity_at"]
        assert item["last_response_status"] == "awaiting_reply"


def test_role_visibility_uses_database_role_not_forged_mapping(
    command_center_context,
):
    context = command_center_context
    owner = context["owner"]
    researcher = context["researcher"]
    other_researcher = context["other_researcher"]
    manager = context["manager"]
    other_manager = context["other_manager"]

    with database.get_db() as db:
        own_research = _lead(
            db,
            company="Researcher Visible",
            creator_id=researcher["id"],
            assignee_id=researcher["id"],
            researcher_id=researcher["id"],
            due_date="2026-08-06",
        )
        hidden_research = _lead(
            db,
            company="Researcher Hidden",
            creator_id=other_researcher["id"],
            assignee_id=other_researcher["id"],
            researcher_id=other_researcher["id"],
            due_date="2026-08-06",
        )
        manager_visible = _lead(
            db,
            company="Manager Visible",
            creator_id=other_researcher["id"],
            assignee_id=owner["id"],
            business_owner_id=manager["id"],
            due_date="2026-08-06",
        )
        _lead(
            db,
            company="Manager Hidden",
            creator_id=other_researcher["id"],
            assignee_id=owner["id"],
            business_owner_id=other_manager["id"],
            due_date="2026-08-06",
        )

        forged_owner = dict(researcher)
        forged_owner["role"] = "owner"
        researcher_center = build_follow_up_command_center(
            db,
            forged_owner,
            today=TODAY,
        )
        researcher_ids = {
            lead["id"]
            for lead in researcher_center[
                "queue_by_key"
            ]["due_today"]["leads"]
        }
        assert own_research["id"] in researcher_ids
        assert hidden_research["id"] not in researcher_ids
        assert manager_visible["id"] not in researcher_ids
        assert researcher_center["actor_role"] == "lead_sourcer"

        manager_center = build_follow_up_command_center(
            db,
            manager,
            today=TODAY,
        )
        manager_ids = {
            lead["id"]
            for lead in manager_center[
                "queue_by_key"
            ]["due_today"]["leads"]
        }
        assert manager_visible["id"] in manager_ids
        assert own_research["id"] not in manager_ids


def test_filters_apply_only_after_role_visibility(
    command_center_context,
):
    context = command_center_context
    owner = context["owner"]
    researcher = context["researcher"]
    other_researcher = context["other_researcher"]
    manager = context["manager"]

    with database.get_db() as db:
        matching = _lead(
            db,
            company="Matching Filters",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            researcher_id=researcher["id"],
            business_owner_id=manager["id"],
            due_date="2026-08-06",
        )
        _lead(
            db,
            company="Different Researcher",
            creator_id=other_researcher["id"],
            assignee_id=owner["id"],
            researcher_id=other_researcher["id"],
            business_owner_id=manager["id"],
            due_date="2026-08-06",
        )

        filtered = build_follow_up_command_center(
            db,
            owner,
            today=TODAY,
            assignee_id=owner["id"],
            researcher_id=researcher["id"],
            business_development_owner_id=manager["id"],
        )
        assert filtered["filtered_lead_count"] == 1
        assert filtered["queue_by_key"]["due_today"]["leads"][0]["id"] == (
            matching["id"]
        )
        assert filtered["selected_filters"] == {
            "assignee_id": owner["id"],
            "researcher_id": researcher["id"],
            "business_development_owner_id": manager["id"],
        }

        with pytest.raises(
            FollowUpFilterError,
            match="positive integer",
        ):
            build_follow_up_command_center(
                db,
                owner,
                today=TODAY,
                researcher_id=0,
            )


def test_due_this_week_excludes_today_and_dates_after_sunday(
    command_center_context,
):
    context = command_center_context
    owner = context["owner"]
    researcher = context["researcher"]

    with database.get_db() as db:
        _lead(
            db,
            company="Thursday Due",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            due_date="2026-08-06",
        )
        friday = _lead(
            db,
            company="Friday Due",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            due_date="2026-08-07",
        )
        sunday = _lead(
            db,
            company="Sunday Due",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            due_date="2026-08-09",
        )
        _lead(
            db,
            company="Monday Due",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            due_date="2026-08-10",
        )

        center = build_follow_up_command_center(
            db,
            owner,
            today=TODAY,
        )
        ids = [
            lead["id"]
            for lead in center[
                "queue_by_key"
            ]["due_this_week"]["leads"]
        ]
        assert ids == [
            friday["id"],
            sunday["id"],
        ]

        sunday_center = build_follow_up_command_center(
            db,
            owner,
            today=date(2026, 8, 9),
        )
        assert sunday_center["queue_by_key"][
            "due_this_week"
        ]["count"] == 0


def test_non_crm_and_inactive_users_fail_closed(
    command_center_context,
):
    context = command_center_context

    with database.get_db() as db:
        for actor in (
            context["member"],
            context["inactive"],
            None,
        ):
            with pytest.raises(
                FollowUpPermissionError,
                match="CRM",
            ):
                build_follow_up_command_center(
                    db,
                    actor,
                    today=TODAY,
                )
