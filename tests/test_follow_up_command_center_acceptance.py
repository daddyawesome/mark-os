from __future__ import annotations

from datetime import date, datetime, timezone
import re

import pytest
from fastapi import Request

from app import database
from app.routes import client_hunting
from app.services.follow_up_command_center import (
    build_follow_up_command_center,
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


def _owner(db) -> dict:
    owner_id = get_primary_owner_id(db)
    return dict(
        db.execute(
            """
            SELECT id, username, display_name, role, active
            FROM users
            WHERE id = ?
            """,
            (owner_id,),
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
    due_date: str | None = None,
    pipeline_status: str = "new",
) -> dict:
    created = create_lead(
        db,
        company=company,
        contact_person="Alex Buyer",
        job_title="Founder",
        source="LinkedIn",
        source_url=(
            "https://example.com/"
            + re.sub(
                r"[^a-z0-9]+",
                "-",
                company.casefold(),
            ).strip("-")
        ),
        problem_opportunity=(
            "Follow-up visibility must stay deterministic."
        ),
        why_mark_fits=(
            "Mark can build and operate the workflow."
        ),
        pipeline_status="new",
        priority="high",
        next_action="Complete the next CRM action.",
        next_action_due_date=due_date,
        notes="Phase 6.4C acceptance fixture.",
        request_key=(
            "phase-6-4c-"
            + re.sub(
                r"[^a-z0-9]+",
                "-",
                company.casefold(),
            ).strip("-")
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
            pipeline_status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            researcher_id,
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


def _external_activity(
    db,
    *,
    owner: dict,
    lead_id: int,
    activity_at: str,
    response_status: str = "replied",
    next_follow_up_date: str | None = None,
    responsible_user_id: int | None = None,
):
    return create_activity(
        db,
        lead_id,
        actor=owner,
        activity_type="email_sent",
        activity_at=activity_at,
        channel="email",
        message_summary="Recorded external contact.",
        notes="",
        performed_by_user_id=owner["id"],
        responsible_user_id=responsible_user_id,
        response_status=response_status,
        next_follow_up_date=next_follow_up_date,
    )


@pytest.fixture
def acceptance_context(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / "phase-6-4c.db",
    )
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner = _owner(db)
        researcher = dict(
            create_lead_sourcer(
                db,
                username="acceptance-researcher",
                display_name="Acceptance Researcher",
                password="temporary-pass-123",
                password_confirmation="temporary-pass-123",
            )
        )
        hidden_researcher = dict(
            create_lead_sourcer(
                db,
                username="hidden-acceptance-researcher",
                display_name="Hidden Acceptance Researcher",
                password="temporary-pass-456",
                password_confirmation="temporary-pass-456",
            )
        )
        manager = dict(
            create_relationship_manager(
                db,
                username="acceptance-manager",
                display_name="Acceptance Manager",
                password="temporary-pass-789",
                password_confirmation="temporary-pass-789",
            )
        )
        hidden_manager = dict(
            create_relationship_manager(
                db,
                username="hidden-acceptance-manager",
                display_name="Hidden Acceptance Manager",
                password="temporary-pass-999",
                password_confirmation="temporary-pass-999",
            )
        )

        researcher_visible = _lead(
            db,
            company="Researcher Visible Acceptance",
            creator_id=researcher["id"],
            assignee_id=researcher["id"],
            researcher_id=researcher["id"],
            business_owner_id=manager["id"],
            due_date="2026-08-06",
        )
        manager_visible = _lead(
            db,
            company="Manager Visible Acceptance",
            creator_id=hidden_researcher["id"],
            assignee_id=owner["id"],
            business_owner_id=manager["id"],
            due_date="2026-08-06",
        )
        hidden = _lead(
            db,
            company="Hidden Foreign Acceptance",
            creator_id=hidden_researcher["id"],
            assignee_id=hidden_researcher["id"],
            researcher_id=hidden_researcher["id"],
            business_owner_id=hidden_manager["id"],
            due_date="2026-08-06",
        )

    original_builder = (
        client_hunting.build_follow_up_command_center
    )

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
        "hidden_researcher": hidden_researcher,
        "manager": manager,
        "hidden_manager": hidden_manager,
        "researcher_visible_id": int(
            researcher_visible["id"]
        ),
        "manager_visible_id": int(
            manager_visible["id"]
        ),
        "hidden_id": int(hidden["id"]),
    }


def test_relationship_manager_page_hides_foreign_records_and_filter_names(
    acceptance_context,
):
    context = acceptance_context
    page = client_hunting.follow_up_command_center_page(
        _request(context["manager"]),
    )
    body = page.body.decode("utf-8")
    compact = " ".join(body.split())

    assert page.status_code == 200
    assert "Manager Visible Acceptance" in body
    assert "Researcher Visible Acceptance" in body
    assert "Hidden Foreign Acceptance" not in body
    assert "Hidden Acceptance Manager" not in body
    assert (
        "Hidden Acceptance Researcher"
        not in body
    )
    assert (
        f'/crm/leads/{context["hidden_id"]}'
        not in body
    )
    assert "2 OF 2 VISIBLE LEADS" in compact
    assert '<form method="get"' in body

    main_match = re.search(
        r"<main\b[^>]*>(.*?)</main>",
        body,
        flags=re.DOTALL,
    )
    assert main_match is not None
    assert 'method="post"' not in main_match.group(1)

    active_follow_up = re.search(
        r'class="mark-sidebar-link\s+is-active"'
        r'\s+href="/crm/follow-ups"',
        body,
    )
    assert active_follow_up is not None

    active_crm = re.search(
        r'class="mark-sidebar-link\s+is-active"'
        r'\s+href="/crm"',
        body,
    )
    assert active_crm is None


def test_database_role_truth_limits_forged_researcher_page(
    acceptance_context,
):
    context = acceptance_context
    forged_owner = dict(context["researcher"])
    forged_owner["role"] = "owner"

    page = client_hunting.follow_up_command_center_page(
        _request(forged_owner),
    )
    body = page.body.decode("utf-8")
    compact = " ".join(body.split())

    assert "Researcher Visible Acceptance" in body
    assert "Manager Visible Acceptance" not in body
    assert "Hidden Foreign Acceptance" not in body
    assert "1 OF 1 VISIBLE LEADS" in compact


def test_all_empty_queues_render_explicit_safe_states(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / "phase-6-4c-empty.db",
    )
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner = _owner(db)

    original_builder = (
        client_hunting.build_follow_up_command_center
    )

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

    page = client_hunting.follow_up_command_center_page(
        _request(owner),
    )
    body = page.body.decode("utf-8")
    compact = " ".join(body.split())

    assert page.status_code == 200
    assert body.count('data-empty-queue="') == 10
    assert "0 OF 0 VISIBLE LEADS" in compact
    for message in (
        "Nothing is due today.",
        "No follow-up work is overdue.",
        "Nothing else is due this week.",
        "No visible leads are waiting for a reply.",
        "No contacted leads are stale.",
        "No approved leads are waiting for first contact.",
        "No research is awaiting review.",
        "No research changes are outstanding.",
        "No interested replies need handoff.",
        "No proposal follow-up currently requires action.",
    ):
        assert message in body


def test_manila_midnight_and_stale_contact_cutoffs_reclassify_exactly(
    acceptance_context,
):
    context = acceptance_context
    owner = context["owner"]
    researcher = context["researcher"]

    with database.get_db() as db:
        midnight_due = _lead(
            db,
            company="Midnight Boundary Due",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            due_date="2026-08-06",
        )
        stale_before_midnight = _lead(
            db,
            company="Stale Before Manila Midnight",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            pipeline_status="contacted",
        )
        fresh_at_midnight = _lead(
            db,
            company="Fresh At Manila Midnight",
            creator_id=researcher["id"],
            assignee_id=owner["id"],
            pipeline_status="contacted",
        )

        _external_activity(
            db,
            owner=owner,
            lead_id=stale_before_midnight["id"],
            activity_at="2026-08-01T15:59:59+00:00",
        )
        _external_activity(
            db,
            owner=owner,
            lead_id=fresh_at_midnight["id"],
            activity_at="2026-08-01T16:00:00+00:00",
        )

        before_midnight = (
            build_follow_up_command_center(
                db,
                owner,
                now_utc=datetime(
                    2026,
                    8,
                    5,
                    15,
                    59,
                    59,
                    tzinfo=timezone.utc,
                ),
            )
        )
        after_midnight = (
            build_follow_up_command_center(
                db,
                owner,
                now_utc=datetime(
                    2026,
                    8,
                    5,
                    16,
                    0,
                    0,
                    tzinfo=timezone.utc,
                ),
            )
        )

        before_due_today_ids = {
            lead["id"]
            for lead in before_midnight[
                "queue_by_key"
            ]["due_today"]["leads"]
        }
        before_week_ids = {
            lead["id"]
            for lead in before_midnight[
                "queue_by_key"
            ]["due_this_week"]["leads"]
        }
        after_due_today_ids = {
            lead["id"]
            for lead in after_midnight[
                "queue_by_key"
            ]["due_today"]["leads"]
        }

        assert midnight_due["id"] not in before_due_today_ids
        assert midnight_due["id"] in before_week_ids
        assert midnight_due["id"] in after_due_today_ids

        stale_ids = {
            lead["id"]
            for lead in after_midnight[
                "queue_by_key"
            ]["no_contact_five_days"]["leads"]
        }
        assert stale_before_midnight["id"] in stale_ids
        assert fresh_at_midnight["id"] not in stale_ids


def test_service_and_rendering_are_read_only_for_crm_and_xp(
    acceptance_context,
):
    context = acceptance_context

    def snapshot(db) -> dict[str, list[tuple]]:
        return {
            table: [
                tuple(row)
                for row in db.execute(
                    f"SELECT * FROM {table} ORDER BY id"
                ).fetchall()
            ]
            for table in (
                "leads",
                "lead_activities",
                "tasks",
                "game_state",
                "xp_ledger",
            )
        }

    with database.get_db() as db:
        before = snapshot(db)

        build_follow_up_command_center(
            db,
            context["owner"],
            today=TODAY,
            assignee_id=context["owner"]["id"],
        )

        after_service = snapshot(db)
        assert after_service == before

    page = client_hunting.follow_up_command_center_page(
        _request(
            context["owner"],
            query_string=(
                f"assignee_id={context['owner']['id']}"
            ),
        ),
        assignee_id=context["owner"]["id"],
    )
    assert page.status_code == 200

    with database.get_db() as db:
        after_render = snapshot(db)

    assert after_render == before
