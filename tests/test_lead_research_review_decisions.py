from __future__ import annotations

import pytest

from app import database
from app.services.lead_research_permissions import (
    LeadPermissionError,
    can_edit_research,
    can_review_research,
    can_submit_for_review,
)
from app.services.lead_research_workflow import (
    list_research_review_queue,
    review_research,
    submit_research_for_review,
    update_research_details,
)
from app.services.leads import create_lead
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

OTHER_SOURCER = {
    "id": 3,
    "username": "other",
    "role": "lead_sourcer",
}


@pytest.fixture
def review_database(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "owner-review.db"
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
        for user_id, username in (
            (BROTHER["id"], BROTHER["username"]),
            (
                OTHER_SOURCER["id"],
                OTHER_SOURCER["username"],
            ),
        ):
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
                VALUES (
                    ?, ?, ?, ?,
                    'lead_sourcer',
                    1,
                    0
                )
                """,
                (
                    user_id,
                    username,
                    username.title(),
                    hash_password(
                        "test-password-123"
                    ),
                ),
            )

    return path


def _create_submitted_lead(
    db,
    *,
    company: str = "Review Analytics",
):
    lead = create_lead(
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
            "Reporting is manual."
        ),
        why_mark_fits=(
            "Mark can automate reporting."
        ),
        pipeline_status="new",
        priority="medium",
        next_action="Review research.",
        next_action_due_date="2026-08-12",
        notes="Research complete.",
        created_by_user_id=BROTHER["id"],
        assigned_to_user_id=OWNER["id"],
    ).lead

    return submit_research_for_review(
        db,
        lead["id"],
        actor=BROTHER,
    )


def test_owner_can_approve_submitted_research(
    review_database,
):
    with database.get_db() as db:
        lead = _create_submitted_lead(db)

        reviewed = review_research(
            db,
            lead["id"],
            actor=OWNER,
            decision="approved",
            review_notes="Research verified.",
        )

        assert (
            reviewed["research_status"]
            == "approved"
        )
        assert (
            reviewed["reviewed_by_user_id"]
            == OWNER["id"]
        )
        assert reviewed["reviewed_at"] is not None
        assert (
            reviewed["review_notes"]
            == "Research verified."
        )
        assert (
            reviewed[
                "outreach_approved_by_user_id"
            ]
            is None
        )
        assert (
            reviewed["outreach_approved_at"]
            is None
        )
        assert not can_review_research(
            OWNER,
            reviewed,
        )
        assert not can_edit_research(
            BROTHER,
            reviewed,
        )

        event = db.execute(
            """
            SELECT event_type
            FROM quest_updates
            WHERE task_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (reviewed["quest_id"],),
        ).fetchone()
        assert (
            event["event_type"]
            == "crm_research_approved"
        )


def test_owner_can_request_changes_with_notes(
    review_database,
):
    with database.get_db() as db:
        lead = _create_submitted_lead(db)

        reviewed = review_research(
            db,
            lead["id"],
            actor=OWNER,
            decision="changes_requested",
            review_notes=(
                "Verify the contact title and budget."
            ),
        )

        assert (
            reviewed["research_status"]
            == "changes_requested"
        )
        assert (
            reviewed["reviewed_by_user_id"]
            == OWNER["id"]
        )
        assert can_edit_research(
            BROTHER,
            reviewed,
        )
        assert can_submit_for_review(
            BROTHER,
            reviewed,
        )

        event = db.execute(
            """
            SELECT event_type
            FROM quest_updates
            WHERE task_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (reviewed["quest_id"],),
        ).fetchone()
        assert (
            event["event_type"]
            == "crm_research_changes_requested"
        )


def test_owner_can_reject_with_notes(
    review_database,
):
    with database.get_db() as db:
        lead = _create_submitted_lead(db)

        reviewed = review_research(
            db,
            lead["id"],
            actor=OWNER,
            decision="rejected",
            review_notes=(
                "The opportunity is not actionable."
            ),
        )

        assert (
            reviewed["research_status"]
            == "rejected"
        )
        assert not can_edit_research(
            BROTHER,
            reviewed,
        )

        event = db.execute(
            """
            SELECT event_type
            FROM quest_updates
            WHERE task_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (reviewed["quest_id"],),
        ).fetchone()
        assert (
            event["event_type"]
            == "crm_research_rejected"
        )


@pytest.mark.parametrize(
    "decision",
    [
        "changes_requested",
        "rejected",
    ],
)
def test_changes_and_rejection_require_notes(
    review_database,
    decision,
):
    with database.get_db() as db:
        lead = _create_submitted_lead(db)

        with pytest.raises(
            ValueError,
            match="notes are required",
        ):
            review_research(
                db,
                lead["id"],
                actor=OWNER,
                decision=decision,
                review_notes="   ",
            )

        unchanged = db.execute(
            """
            SELECT
                research_status,
                reviewed_by_user_id,
                reviewed_at
            FROM leads
            WHERE id = ?
            """,
            (lead["id"],),
        ).fetchone()
        assert (
            unchanged["research_status"]
            == "ready_for_review"
        )
        assert (
            unchanged["reviewed_by_user_id"]
            is None
        )
        assert unchanged["reviewed_at"] is None


def test_non_owner_cannot_review_research(
    review_database,
):
    with database.get_db() as db:
        lead = _create_submitted_lead(db)

        with pytest.raises(
            LeadPermissionError,
            match="not allowed",
        ):
            review_research(
                db,
                lead["id"],
                actor=BROTHER,
                decision="approved",
            )


def test_only_ready_for_review_state_can_be_decided(
    review_database,
):
    with database.get_db() as db:
        lead = _create_submitted_lead(db)
        approved = review_research(
            db,
            lead["id"],
            actor=OWNER,
            decision="approved",
        )

        with pytest.raises(
            LeadPermissionError,
            match="not allowed",
        ):
            review_research(
                db,
                approved["id"],
                actor=OWNER,
                decision="rejected",
                review_notes="No.",
            )


def test_invalid_decision_does_not_mutate_lead(
    review_database,
):
    with database.get_db() as db:
        lead = _create_submitted_lead(db)

        with pytest.raises(
            ValueError,
            match="Unsupported",
        ):
            review_research(
                db,
                lead["id"],
                actor=OWNER,
                decision="publish",
                review_notes="Invalid.",
            )

        unchanged = db.execute(
            """
            SELECT
                research_status,
                reviewed_by_user_id
            FROM leads
            WHERE id = ?
            """,
            (lead["id"],),
        ).fetchone()
        assert (
            unchanged["research_status"]
            == "ready_for_review"
        )
        assert (
            unchanged["reviewed_by_user_id"]
            is None
        )


def test_decided_lead_leaves_owner_queue(
    review_database,
):
    with database.get_db() as db:
        first = _create_submitted_lead(
            db,
            company="First Review",
        )
        second = _create_submitted_lead(
            db,
            company="Second Review",
        )

        review_research(
            db,
            first["id"],
            actor=OWNER,
            decision="approved",
        )

        queue = list_research_review_queue(db)

        assert [
            row["company"]
            for row in queue
        ] == ["Second Review"]
        assert second["id"] == queue[0]["id"]


def test_resubmission_clears_old_reviewer_metadata(
    review_database,
):
    with database.get_db() as db:
        lead = _create_submitted_lead(db)

        changed = review_research(
            db,
            lead["id"],
            actor=OWNER,
            decision="changes_requested",
            review_notes="Verify the decision maker.",
        )

        edited = update_research_details(
            db,
            changed["id"],
            actor=BROTHER,
            company=changed["company"],
            contact_person=(
                changed["contact_person"]
            ),
            job_title=changed["job_title"],
            source=changed["source"],
            source_url=changed["source_url"],
            problem_opportunity=(
                changed["problem_opportunity"]
            ),
            why_mark_fits=(
                changed["why_mark_fits"]
            ),
            next_action=changed["next_action"],
            next_action_due_date=(
                changed["next_action_due_date"]
            ),
            notes=(
                "Decision maker verified. "
                + changed["notes"]
            ),
        )

        resubmitted = submit_research_for_review(
            db,
            edited["id"],
            actor=BROTHER,
        )

        assert (
            resubmitted["research_status"]
            == "ready_for_review"
        )
        assert (
            resubmitted["reviewed_by_user_id"]
            is None
        )
        assert resubmitted["reviewed_at"] is None
        assert (
            resubmitted["review_notes"]
            == "Verify the decision maker."
        )


def test_review_notes_length_is_limited(
    review_database,
):
    with database.get_db() as db:
        lead = _create_submitted_lead(db)

        with pytest.raises(
            ValueError,
            match="2000",
        ):
            review_research(
                db,
                lead["id"],
                actor=OWNER,
                decision="approved",
                review_notes="x" * 2001,
            )
