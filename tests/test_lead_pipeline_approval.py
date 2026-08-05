from __future__ import annotations

import pytest

from app import database
from app.services.lead_pipeline_workflow import (
    LeadPipelineRuleError,
    approve_outreach,
    change_pipeline_stage,
    update_owner_lead,
)
from app.services.lead_research_permissions import (
    LeadPermissionError,
)
from app.services.lead_research_workflow import (
    review_research,
    submit_research_for_review,
)
from app.services.leads import create_lead, get_lead
from app.services.passwords import hash_password


OWNER = {
    "id": 1,
    "username": "mark",
    "role": "owner",
}

BROTHER = {
    "id": 2,
    "username": "brother",
    "role": "lead_sourcer",
}

MEMBER = {
    "id": 3,
    "username": "member",
    "role": "member",
}


@pytest.fixture
def pipeline_database(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "phase-6-1f.db"
    monkeypatch.setattr(
        database,
        "DB_PATH",
        path,
    )
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
    database.init_db()

    with database.get_db() as db:
        for actor in (BROTHER, MEMBER):
            db.execute(
                """
                INSERT INTO users (
                    id,
                    username,
                    display_name,
                    password_hash,
                    role,
                    active,
                    must_change_password
                )
                VALUES (?, ?, ?, ?, ?, 1, 0)
                """,
                (
                    actor["id"],
                    actor["username"],
                    actor["username"].title(),
                    hash_password(
                        "test-password-123"
                    ),
                    actor["role"],
                ),
            )
    return path


def _create_lead(
    db,
    *,
    company: str = "Pipeline Analytics",
):
    return create_lead(
        db,
        company=company,
        contact_person="Dana Buyer",
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
        next_action="Complete research review.",
        next_action_due_date="2026-08-20",
        notes="Initial research.",
        created_by_user_id=BROTHER["id"],
        assigned_to_user_id=OWNER["id"],
    ).lead


def _create_approved_lead(
    db,
    *,
    company: str = "Pipeline Analytics",
):
    created = _create_lead(
        db,
        company=company,
    )
    submitted = submit_research_for_review(
        db,
        created["id"],
        actor=BROTHER,
    )
    return review_research(
        db,
        submitted["id"],
        actor=OWNER,
        decision="approved",
        review_notes="Research verified.",
    )


def test_owner_approves_outreach_once(
    pipeline_database,
):
    with database.get_db() as db:
        lead = _create_approved_lead(db)

        first = approve_outreach(
            db,
            lead["id"],
            actor=OWNER,
        )
        second = approve_outreach(
            db,
            lead["id"],
            actor=OWNER,
        )

        assert (
            first["outreach_approved_by_user_id"]
            == OWNER["id"]
        )
        assert first["outreach_approved_at"] is not None
        assert (
            second["outreach_approved_at"]
            == first["outreach_approved_at"]
        )

        event_count = db.execute(
            """
            SELECT COUNT(*)
            FROM quest_updates
            WHERE task_id = ?
              AND event_type = 'crm_outreach_approved'
            """,
            (lead["quest_id"],),
        ).fetchone()[0]
        assert event_count == 1


@pytest.mark.parametrize(
    "actor",
    [BROTHER, MEMBER],
)
def test_non_owner_cannot_approve_outreach(
    pipeline_database,
    actor,
):
    with database.get_db() as db:
        lead = _create_approved_lead(
            db,
            company=(
                "Unauthorized "
                + actor["username"]
            ),
        )

        with pytest.raises(
            LeadPermissionError,
            match="Only the Owner",
        ):
            approve_outreach(
                db,
                lead["id"],
                actor=actor,
            )

        unchanged = get_lead(db, lead["id"])
        assert (
            unchanged[
                "outreach_approved_by_user_id"
            ]
            is None
        )
        assert (
            unchanged["outreach_approved_at"]
            is None
        )


def test_unapproved_research_cannot_receive_outreach_approval(
    pipeline_database,
):
    with database.get_db() as db:
        lead = _create_lead(
            db,
            company="Unreviewed Analytics",
        )

        with pytest.raises(
            LeadPermissionError,
            match="Only the Owner",
        ):
            approve_outreach(
                db,
                lead["id"],
                actor=OWNER,
            )


def test_contacted_requires_outreach_approval(
    pipeline_database,
):
    with database.get_db() as db:
        lead = _create_approved_lead(
            db,
            company="Contact Gate",
        )

        with pytest.raises(
            LeadPipelineRuleError,
            match="outreach approval",
        ):
            change_pipeline_stage(
                db,
                lead["id"],
                actor=OWNER,
                pipeline_status="contacted",
            )

        approve_outreach(
            db,
            lead["id"],
            actor=OWNER,
        )
        contacted = change_pipeline_stage(
            db,
            lead["id"],
            actor=OWNER,
            pipeline_status="contacted",
        )

        assert (
            contacted["pipeline_status"]
            == "contacted"
        )
        quest = db.execute(
            """
            SELECT status, progress, xp_reward
            FROM tasks
            WHERE id = ?
            """,
            (contacted["quest_id"],),
        ).fetchone()
        assert quest["status"] == "active"
        assert quest["progress"] == 25
        assert quest["xp_reward"] == 0


def test_proposal_and_won_require_prior_major_stage(
    pipeline_database,
):
    with database.get_db() as db:
        lead = _create_approved_lead(
            db,
            company="Major Stage Gate",
        )

        with pytest.raises(
            LeadPipelineRuleError,
            match="Meeting",
        ):
            change_pipeline_stage(
                db,
                lead["id"],
                actor=OWNER,
                pipeline_status="proposal",
            )

        meeting = change_pipeline_stage(
            db,
            lead["id"],
            actor=OWNER,
            pipeline_status="meeting",
        )
        proposal = change_pipeline_stage(
            db,
            meeting["id"],
            actor=OWNER,
            pipeline_status="proposal",
        )
        won = change_pipeline_stage(
            db,
            proposal["id"],
            actor=OWNER,
            pipeline_status="won",
        )

        assert meeting["pipeline_status"] == "meeting"
        assert (
            proposal["pipeline_status"]
            == "proposal"
        )
        assert won["pipeline_status"] == "won"


@pytest.mark.parametrize(
    "actor",
    [BROTHER, MEMBER],
)
def test_non_owner_cannot_change_pipeline(
    pipeline_database,
    actor,
):
    with database.get_db() as db:
        lead = _create_approved_lead(
            db,
            company=(
                "Forged Pipeline "
                + actor["username"]
            ),
        )

        with pytest.raises(
            LeadPermissionError,
            match="Only the Owner",
        ):
            change_pipeline_stage(
                db,
                lead["id"],
                actor=actor,
                pipeline_status="lost",
            )

        assert (
            get_lead(db, lead["id"])[
                "pipeline_status"
            ]
            == "new"
        )


def test_full_edit_cannot_bypass_contacted_gate(
    pipeline_database,
):
    with database.get_db() as db:
        lead = _create_approved_lead(
            db,
            company="Full Edit Gate",
        )

        with pytest.raises(
            LeadPipelineRuleError,
            match="outreach approval",
        ):
            update_owner_lead(
                db,
                lead["id"],
                actor=OWNER,
                company="Should Not Save",
                contact_person=lead[
                    "contact_person"
                ],
                job_title=lead["job_title"],
                source=lead["source"],
                source_url=lead["source_url"],
                problem_opportunity=lead[
                    "problem_opportunity"
                ],
                why_mark_fits=lead[
                    "why_mark_fits"
                ],
                pipeline_status="contacted",
                priority=lead["priority"],
                next_action=lead["next_action"],
                next_action_due_date=lead[
                    "next_action_due_date"
                ],
                notes=lead["notes"],
            )

        unchanged = get_lead(db, lead["id"])
        assert unchanged["company"] == "Full Edit Gate"
        assert unchanged["pipeline_status"] == "new"

        approve_outreach(
            db,
            lead["id"],
            actor=OWNER,
        )
        updated = update_owner_lead(
            db,
            lead["id"],
            actor=OWNER,
            company="Approved Contact",
            contact_person=lead["contact_person"],
            job_title=lead["job_title"],
            source=lead["source"],
            source_url=lead["source_url"],
            problem_opportunity=lead[
                "problem_opportunity"
            ],
            why_mark_fits=lead["why_mark_fits"],
            pipeline_status="contacted",
            priority=lead["priority"],
            next_action="Send approved outreach.",
            next_action_due_date=lead[
                "next_action_due_date"
            ],
            notes=lead["notes"],
        )
        assert updated["company"] == "Approved Contact"
        assert updated["pipeline_status"] == "contacted"


def test_phase_6_1f_does_not_change_xp(
    pipeline_database,
):
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

        lead = _create_approved_lead(
            db,
            company="No XP Pipeline",
        )
        approve_outreach(
            db,
            lead["id"],
            actor=OWNER,
        )
        change_pipeline_stage(
            db,
            lead["id"],
            actor=OWNER,
            pipeline_status="contacted",
        )
        change_pipeline_stage(
            db,
            lead["id"],
            actor=OWNER,
            pipeline_status="lost",
        )

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
