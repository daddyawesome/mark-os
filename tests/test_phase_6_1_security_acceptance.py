from __future__ import annotations

import asyncio

import pytest
from fastapi import Request
from fastapi.responses import PlainTextResponse

from app import database
import app.main as main_module
from app.services.access_control import (
    can_access_request,
)
from app.services.lead_pipeline_workflow import (
    approve_outreach,
    change_pipeline_stage,
)
from app.services.lead_research_permissions import (
    LeadPermissionError,
    can_view_lead,
)
from app.services.lead_research_workflow import (
    review_research,
    submit_research_for_review,
    update_research_details,
)
from app.services.lead_work_queues import (
    build_role_aware_crm_dashboard,
)
from app.services.leads import create_lead, get_lead
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
def phase_6_1_database(tmp_path, monkeypatch):
    path = tmp_path / "phase-6-1-acceptance.db"
    monkeypatch.setattr(
        database,
        "DB_PATH",
        path,
    )
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db)
        owner_row = db.execute(
            """
            SELECT
                id,
                username,
                display_name,
                role
            FROM users
            WHERE id = ?
            """,
            (owner_id,),
        ).fetchone()

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
        member = db.execute(
            """
            SELECT
                id,
                username,
                display_name,
                role
            FROM users
            WHERE id = ?
            """,
            (member_id,),
        ).fetchone()

    return {
        "path": path,
        "owner": dict(owner_row),
        "brother": dict(brother),
        "other": dict(other),
        "member": dict(member),
    }


def _create_lead(
    db,
    *,
    company: str,
    creator_id: int,
    assignee_id: int,
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
            "The company still prepares reports "
            "manually."
        ),
        why_mark_fits=(
            "Mark can automate the reporting process."
        ),
        pipeline_status="new",
        priority="high",
        next_action="Complete lead research.",
        next_action_due_date="2026-08-20",
        notes="Phase 6.1 acceptance fixture.",
        request_key=(
            "phase-6-1-"
            + company.casefold().replace(" ", "-")
        ),
        created_by_user_id=creator_id,
        assigned_to_user_id=assignee_id,
    ).lead


def _save_research(
    db,
    lead,
    actor,
    *,
    company: str | None = None,
    notes: str = "Research evidence verified.",
):
    return update_research_details(
        db,
        lead["id"],
        actor=actor,
        company=company or lead["company"],
        contact_person=lead["contact_person"],
        job_title=lead["job_title"],
        source=lead["source"],
        source_url=lead["source_url"],
        problem_opportunity=(
            "Manual reporting creates delays and "
            "avoidable rework."
        ),
        why_mark_fits=(
            "Mark has Power BI, SQL, Python, and "
            "automation experience."
        ),
        next_action="Submit research for review.",
        next_action_due_date="2026-08-20",
        notes=notes,
    )


def _game_state_snapshot(db):
    return [
        tuple(row)
        for row in db.execute(
            """
            SELECT
                id,
                user_id,
                level,
                xp_total,
                xp_into_level,
                last_level_up_at
            FROM game_state
            ORDER BY id
            """
        ).fetchall()
    ]


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


@pytest.mark.parametrize(
    "method,path",
    (
        (
            "POST",
            "/crm/leads/1/research/review",
        ),
        (
            "POST",
            "/crm/leads/1/outreach/approve",
        ),
        (
            "POST",
            "/crm/leads/1/pipeline",
        ),
        (
            "POST",
            "/crm/leads/1/edit",
        ),
        (
            "POST",
            "/crm/leads/1/next-action",
        ),
        (
            "POST",
            "/crm/leads/1/delete",
        ),
        (
            "POST",
            "/settings/users/1/status",
        ),
    ),
)
def test_forged_owner_posts_are_blocked_by_middleware(
    phase_6_1_database,
    monkeypatch,
    method,
    path,
):
    brother = phase_6_1_database["brother"]
    monkeypatch.setattr(
        main_module,
        "current_user",
        lambda request: brother,
    )

    called = {"value": False}

    async def call_next(request):
        called["value"] = True
        return PlainTextResponse(
            "must not execute"
        )

    response = asyncio.run(
        main_module.login_and_permission_guard(
            _request(method, path),
            call_next,
        )
    )

    assert response.status_code == 403
    assert response.body == b"Forbidden"
    assert called["value"] is False


@pytest.mark.parametrize(
    "path",
    (
        "/",
        "/quests",
        "/history",
        "/life-os",
        "/goals",
        "/crm/research-review",
        "/crm/leads/1/edit",
        "/crm/leads/1/delete",
        "/settings/users",
    ),
)
def test_direct_owner_pages_redirect_lead_researcher(
    phase_6_1_database,
    monkeypatch,
    path,
):
    brother = phase_6_1_database["brother"]
    monkeypatch.setattr(
        main_module,
        "current_user",
        lambda request: brother,
    )

    async def call_next(request):
        return PlainTextResponse(
            "must not execute"
        )

    response = asyncio.run(
        main_module.login_and_permission_guard(
            _request("GET", path),
            call_next,
        )
    )

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == "/crm?error=forbidden"
    )


def test_allowed_researcher_routes_remain_available(
    phase_6_1_database,
):
    brother = phase_6_1_database["brother"]

    allowed = (
        ("GET", "/crm"),
        ("GET", "/crm/leads/new"),
        ("POST", "/crm/leads"),
        ("POST", "/crm/leads/import"),
        (
            "GET",
            "/crm/leads/12/research/edit",
        ),
        (
            "POST",
            "/crm/leads/12/research/edit",
        ),
        (
            "POST",
            "/crm/leads/12/research/submit",
        ),
    )

    assert all(
        can_access_request(
            brother,
            method,
            path,
        )
        for method, path in allowed
    )


def test_unrelated_lead_is_hidden_and_not_editable(
    phase_6_1_database,
):
    owner = phase_6_1_database["owner"]
    brother = phase_6_1_database["brother"]
    other = phase_6_1_database["other"]

    with database.get_db() as db:
        lead = _create_lead(
            db,
            company="Private Other Research",
            creator_id=other["id"],
            assignee_id=owner["id"],
        )

        assert not can_view_lead(
            brother,
            lead,
        )

        dashboard = (
            build_role_aware_crm_dashboard(
                db,
                brother,
            )
        )
        visible_ids = {
            row["id"]
            for row in dashboard["leads"]
        }
        assert lead["id"] not in visible_ids

        with pytest.raises(
            LeadPermissionError,
        ):
            _save_research(
                db,
                lead,
                brother,
            )

        with pytest.raises(
            LeadPermissionError,
        ):
            submit_research_for_review(
                db,
                lead["id"],
                actor=brother,
            )


def test_complete_staff_review_and_outreach_workflow(
    phase_6_1_database,
):
    owner = phase_6_1_database["owner"]
    brother = phase_6_1_database["brother"]

    with database.get_db() as db:
        xp_before = _game_state_snapshot(db)
        ledger_before = db.execute(
            "SELECT COUNT(*) FROM xp_ledger"
        ).fetchone()[0]

        lead = _create_lead(
            db,
            company="Complete Workflow Co",
            creator_id=brother["id"],
            assignee_id=owner["id"],
        )

        researching = _save_research(
            db,
            lead,
            brother,
        )
        assert (
            researching["research_status"]
            == "researching"
        )
        assert (
            researching["researched_by_user_id"]
            == brother["id"]
        )

        submitted = submit_research_for_review(
            db,
            lead["id"],
            actor=brother,
        )
        assert (
            submitted["research_status"]
            == "ready_for_review"
        )
        assert (
            submitted["submitted_for_review_at"]
            is not None
        )

        changes = review_research(
            db,
            lead["id"],
            actor=owner,
            decision="changes_requested",
            review_notes=(
                "Add a stronger source and verify "
                "the decision-maker."
            ),
        )
        assert (
            changes["research_status"]
            == "changes_requested"
        )
        assert (
            changes["reviewed_by_user_id"]
            == owner["id"]
        )
        assert changes["reviewed_at"] is not None

        corrected = _save_research(
            db,
            changes,
            brother,
            notes=(
                "Source and decision-maker verified."
            ),
        )
        assert (
            corrected["research_status"]
            == "researching"
        )
        assert (
            corrected["submitted_for_review_at"]
            is None
        )

        resubmitted = submit_research_for_review(
            db,
            lead["id"],
            actor=brother,
        )
        approved = review_research(
            db,
            resubmitted["id"],
            actor=owner,
            decision="approved",
            review_notes="Research approved.",
        )
        assert (
            approved["research_status"]
            == "approved"
        )
        assert (
            approved["reviewed_by_user_id"]
            == owner["id"]
        )

        outreach = approve_outreach(
            db,
            approved["id"],
            actor=owner,
        )
        assert (
            outreach[
                "outreach_approved_by_user_id"
            ]
            == owner["id"]
        )
        assert (
            outreach["outreach_approved_at"]
            is not None
        )

        contacted = change_pipeline_stage(
            db,
            outreach["id"],
            actor=owner,
            pipeline_status="contacted",
        )
        assert (
            contacted["pipeline_status"]
            == "contacted"
        )

        event_types = [
            row["event_type"]
            for row in db.execute(
                """
                SELECT event_type
                FROM quest_updates
                WHERE task_id = ?
                ORDER BY id
                """,
                (lead["quest_id"],),
            ).fetchall()
        ]
        for expected in (
            "crm_created",
            "crm_research_saved",
            "crm_research_submitted",
            "crm_research_changes_requested",
            "crm_research_approved",
            "crm_outreach_approved",
            "crm_pipeline",
        ):
            assert expected in event_types

        assert _game_state_snapshot(db) == xp_before
        assert (
            db.execute(
                "SELECT COUNT(*) FROM xp_ledger"
            ).fetchone()[0]
            == ledger_before
        )


def test_service_forgery_cannot_make_owner_decisions(
    phase_6_1_database,
):
    owner = phase_6_1_database["owner"]
    brother = phase_6_1_database["brother"]

    with database.get_db() as db:
        lead = _create_lead(
            db,
            company="Service Forgery Co",
            creator_id=brother["id"],
            assignee_id=owner["id"],
        )
        _save_research(
            db,
            lead,
            brother,
        )
        submit_research_for_review(
            db,
            lead["id"],
            actor=brother,
        )

        with pytest.raises(
            LeadPermissionError,
        ):
            review_research(
                db,
                lead["id"],
                actor=brother,
                decision="approved",
                review_notes="Forged approval.",
            )

        approved = review_research(
            db,
            lead["id"],
            actor=owner,
            decision="approved",
            review_notes="Owner approval.",
        )

        with pytest.raises(
            LeadPermissionError,
        ):
            approve_outreach(
                db,
                approved["id"],
                actor=brother,
            )

        approve_outreach(
            db,
            approved["id"],
            actor=owner,
        )

        with pytest.raises(
            LeadPermissionError,
        ):
            change_pipeline_stage(
                db,
                approved["id"],
                actor=brother,
                pipeline_status="contacted",
            )

        unchanged = get_lead(
            db,
            approved["id"],
        )
        assert (
            unchanged["pipeline_status"]
            == "new"
        )


def test_member_has_no_crm_authority(
    phase_6_1_database,
):
    member = phase_6_1_database["member"]

    assert not can_access_request(
        member,
        "GET",
        "/crm",
    )
    assert not can_access_request(
        member,
        "POST",
        "/crm/leads",
    )
    assert not can_access_request(
        member,
        "POST",
        "/crm/leads/1/research/review",
    )
    assert not can_access_request(
        member,
        "POST",
        "/crm/leads/1/outreach/approve",
    )
