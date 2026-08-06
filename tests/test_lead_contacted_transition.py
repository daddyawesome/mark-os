from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Request

from app import database
from app.routes import client_hunting
from app.services import lead_pipeline_workflow
from app.services.lead_pipeline_workflow import (
    LeadPipelineRuleError,
    approve_outreach,
    change_pipeline_stage,
)
from app.services.lead_research_workflow import (
    review_research,
    submit_research_for_review,
)
from app.services.leads import create_lead, get_lead
from app.services.team_users import (
    create_lead_sourcer,
    create_relationship_manager,
    get_primary_owner_id,
)


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
    path: str,
) -> Request:
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
    return request


def _contact_payload(
    responsible_user_id: int,
) -> dict:
    return {
        "contact_activity_type": "email_sent",
        "contact_activity_at": "2026-08-06T19:30",
        "contact_channel": "email",
        "contact_message_summary": (
            "Sent the Owner-approved first introduction."
        ),
        "contact_notes": "Used the approved outreach wording.",
        "contact_responsible_user_id": responsible_user_id,
        "contact_response_status": "awaiting_reply",
        "contact_next_follow_up_date": "2026-08-09",
    }


@pytest.fixture
def contacted_context(tmp_path, monkeypatch):
    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / "phase-6-3d.db",
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
                username="contact-researcher",
                display_name="Contact Researcher",
                password="temporary-pass-123",
                password_confirmation="temporary-pass-123",
            )
        )
        manager = dict(
            create_relationship_manager(
                db,
                username="contact-manager",
                display_name="Contact Manager",
                password="temporary-pass-456",
                password_confirmation="temporary-pass-456",
            )
        )
        lead = create_lead(
            db,
            company="Atomic Contact Company",
            contact_person="Alex Buyer",
            job_title="Founder",
            source="LinkedIn",
            source_url="https://example.com/atomic-contact",
            problem_opportunity="First-contact history is fragmented.",
            why_mark_fits="Mark can build an auditable workflow.",
            pipeline_status="new",
            priority="high",
            next_action="Complete research approval.",
            next_action_due_date="2026-08-08",
            notes="Phase 6.3D fixture.",
            request_key="phase-6-3d-contact",
            created_by_user_id=sourcer["id"],
            assigned_to_user_id=owner["id"],
            business_development_owner_user_id=manager["id"],
        ).lead
        submitted = submit_research_for_review(
            db,
            lead["id"],
            actor=sourcer,
        )
        reviewed = review_research(
            db,
            submitted["id"],
            actor=owner,
            decision="approved",
            review_notes="Research verified.",
        )
        approved = approve_outreach(
            db,
            reviewed["id"],
            actor=owner,
        )

    return {
        "owner": owner,
        "sourcer": sourcer,
        "manager": manager,
        "lead_id": int(approved["id"]),
        "quest_id": int(approved["quest_id"]),
    }


def test_contacted_transition_writes_required_activity_and_preserves_xp(
    contacted_context,
):
    context = contacted_context
    with database.get_db() as db:
        before_state = [
            tuple(row)
            for row in db.execute(
                """
                SELECT
                    id,
                    level,
                    xp_total,
                    xp_into_level,
                    last_level_up_at
                FROM game_state
                ORDER BY id
                """
            ).fetchall()
        ]
        before_ledger = db.execute(
            "SELECT COUNT(*) FROM xp_ledger"
        ).fetchone()[0]

        contacted = change_pipeline_stage(
            db,
            context["lead_id"],
            actor=context["owner"],
            pipeline_status="contacted",
            **_contact_payload(context["manager"]["id"]),
        )

        assert contacted["pipeline_status"] == "contacted"
        activity = db.execute(
            """
            SELECT *
            FROM lead_activities
            WHERE lead_id = ?
              AND deleted_at IS NULL
            """,
            (context["lead_id"],),
        ).fetchone()
        assert activity is not None
        assert activity["activity_type"] == "email_sent"
        assert activity["activity_at"] == "2026-08-06 19:30:00"
        assert activity["channel"] == "email"
        assert activity["message_summary"] == (
            "Sent the Owner-approved first introduction."
        )
        assert activity["created_by_user_id"] == context["owner"]["id"]
        assert activity["performed_by_user_id"] == context["owner"]["id"]
        assert activity["responsible_user_id"] == context["manager"]["id"]
        assert activity["response_status"] == "awaiting_reply"
        assert activity["next_follow_up_date"] == "2026-08-09"

        quest = db.execute(
            """
            SELECT status, progress, xp_reward
            FROM tasks
            WHERE id = ?
            """,
            (context["quest_id"],),
        ).fetchone()
        assert quest["status"] == "active"
        assert quest["progress"] == 25
        assert quest["xp_reward"] == 0

        after_state = [
            tuple(row)
            for row in db.execute(
                """
                SELECT
                    id,
                    level,
                    xp_total,
                    xp_into_level,
                    last_level_up_at
                FROM game_state
                ORDER BY id
                """
            ).fetchall()
        ]
        after_ledger = db.execute(
            "SELECT COUNT(*) FROM xp_ledger"
        ).fetchone()[0]
        assert after_state == before_state
        assert after_ledger == before_ledger


def test_missing_contact_audit_changes_neither_activity_nor_pipeline(
    contacted_context,
):
    context = contacted_context
    with database.get_db() as db:
        with pytest.raises(
            LeadPipelineRuleError,
            match="complete contact audit",
        ):
            change_pipeline_stage(
                db,
                context["lead_id"],
                actor=context["owner"],
                pipeline_status="contacted",
            )

        assert get_lead(
            db,
            context["lead_id"],
        )["pipeline_status"] == "new"
        assert db.execute(
            """
            SELECT COUNT(*)
            FROM lead_activities
            WHERE lead_id = ?
            """,
            (context["lead_id"],),
        ).fetchone()[0] == 0


def test_pipeline_failure_rolls_back_already_inserted_contact_activity(
    contacted_context,
    monkeypatch,
):
    context = contacted_context

    def fail_pipeline_update(*args, **kwargs):
        raise RuntimeError("forced pipeline failure")

    monkeypatch.setattr(
        lead_pipeline_workflow,
        "update_lead_pipeline",
        fail_pipeline_update,
    )

    with database.get_db() as db:
        with pytest.raises(
            RuntimeError,
            match="forced pipeline failure",
        ):
            change_pipeline_stage(
                db,
                context["lead_id"],
                actor=context["owner"],
                pipeline_status="contacted",
                **_contact_payload(context["manager"]["id"]),
            )

        assert get_lead(
            db,
            context["lead_id"],
        )["pipeline_status"] == "new"
        assert db.execute(
            """
            SELECT COUNT(*)
            FROM lead_activities
            WHERE lead_id = ?
            """,
            (context["lead_id"],),
        ).fetchone()[0] == 0


def test_repeating_contacted_state_does_not_duplicate_activity(
    contacted_context,
):
    context = contacted_context
    with database.get_db() as db:
        first = change_pipeline_stage(
            db,
            context["lead_id"],
            actor=context["owner"],
            pipeline_status="contacted",
            **_contact_payload(context["manager"]["id"]),
        )
        second = change_pipeline_stage(
            db,
            context["lead_id"],
            actor=context["owner"],
            pipeline_status="contacted",
        )
        assert first["pipeline_status"] == "contacted"
        assert second["pipeline_status"] == "contacted"
        assert db.execute(
            """
            SELECT COUNT(*)
            FROM lead_activities
            WHERE lead_id = ?
              AND deleted_at IS NULL
            """,
            (context["lead_id"],),
        ).fetchone()[0] == 1


def test_owner_page_and_route_use_dedicated_contacted_form(
    contacted_context,
):
    context = contacted_context
    page = client_hunting.lead_detail(
        _request(
            context["owner"],
            f"/crm/leads/{context['lead_id']}",
        ),
        context["lead_id"],
    )
    body = page.body.decode("utf-8")
    assert "Audited First Contact" in body
    assert "Record Contact and Move to Contacted" in body
    assert 'name="contact_activity_at"' in body
    assert 'name="contact_responsible_user_id"' in body
    assert 'name="contact_next_follow_up_date"' in body

    route_request = SimpleNamespace(
        state=SimpleNamespace(
            current_user=context["owner"]
        )
    )
    rejected = client_hunting.update_pipeline(
        route_request,
        context["lead_id"],
        pipeline_status="contacted",
    )
    assert rejected.status_code == 303
    assert rejected.headers["location"].endswith(
        "?error=pipeline_rule"
    )

    payload = _contact_payload(context["manager"]["id"])
    accepted = client_hunting.update_pipeline(
        route_request,
        context["lead_id"],
        pipeline_status="contacted",
        contact_activity_type=payload["contact_activity_type"],
        contact_activity_at=payload["contact_activity_at"],
        contact_channel=payload["contact_channel"],
        contact_message_summary=payload[
            "contact_message_summary"
        ],
        contact_notes=payload["contact_notes"],
        contact_responsible_user_id=str(
            payload["contact_responsible_user_id"]
        ),
        contact_response_status=payload[
            "contact_response_status"
        ],
        contact_next_follow_up_date=payload[
            "contact_next_follow_up_date"
        ],
    )
    assert accepted.status_code == 303
    assert accepted.headers["location"].endswith(
        "?notice=pipeline"
    )

    with database.get_db() as db:
        assert get_lead(
            db,
            context["lead_id"],
        )["pipeline_status"] == "contacted"
        assert db.execute(
            """
            SELECT COUNT(*)
            FROM lead_activities
            WHERE lead_id = ?
              AND deleted_at IS NULL
            """,
            (context["lead_id"],),
        ).fetchone()[0] == 1
