from __future__ import annotations

import pytest

from app import database
from app.services.lead_research_permissions import (
    LeadPermissionError,
    can_edit_research,
    can_submit_for_review,
)
from app.services.lead_research_workflow import (
    list_research_review_queue,
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
def submission_database(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "research-submit.db"
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


def _create_lead(
    db,
    *,
    company: str = "Review Analytics",
    priority: str = "medium",
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
            "Reporting is manual."
        ),
        why_mark_fits=(
            "Mark can automate reporting."
        ),
        pipeline_status="new",
        priority=priority,
        next_action="Complete research.",
        next_action_due_date="2026-08-10",
        notes="Initial note.",
        created_by_user_id=BROTHER["id"],
        assigned_to_user_id=OWNER["id"],
    ).lead


def test_brother_can_submit_research_for_owner_review(
    submission_database,
):
    with database.get_db() as db:
        lead = _create_lead(db)

        update_research_details(
            db,
            lead["id"],
            actor=BROTHER,
            company=lead["company"],
            contact_person=lead["contact_person"],
            job_title=lead["job_title"],
            source=lead["source"],
            source_url=lead["source_url"],
            problem_opportunity=(
                "Verified manual weekly reporting."
            ),
            why_mark_fits=(
                "Mark has relevant Power BI work."
            ),
            next_action=(
                "Mark reviews the lead research."
            ),
            next_action_due_date=(
                lead["next_action_due_date"]
            ),
            notes="Research complete.",
        )

        submitted = submit_research_for_review(
            db,
            lead["id"],
            actor=BROTHER,
        )

        assert (
            submitted["research_status"]
            == "ready_for_review"
        )
        assert (
            submitted["researched_by_user_id"]
            == BROTHER["id"]
        )
        assert (
            submitted["submitted_for_review_at"]
            is not None
        )
        assert submitted["pipeline_status"] == "new"
        assert submitted["priority"] == "medium"
        assert not can_edit_research(
            BROTHER,
            submitted,
        )
        assert not can_submit_for_review(
            BROTHER,
            submitted,
        )

        event = db.execute(
            """
            SELECT event_type
            FROM quest_updates
            WHERE task_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (submitted["quest_id"],),
        ).fetchone()
        assert (
            event["event_type"]
            == "crm_research_submitted"
        )


def test_ready_for_review_lead_is_locked_from_edits(
    submission_database,
):
    with database.get_db() as db:
        lead = _create_lead(db)
        submitted = submit_research_for_review(
            db,
            lead["id"],
            actor=BROTHER,
        )

        with pytest.raises(
            LeadPermissionError,
            match="not allowed",
        ):
            update_research_details(
                db,
                submitted["id"],
                actor=BROTHER,
                company=submitted["company"],
                contact_person=(
                    submitted["contact_person"]
                ),
                job_title=submitted["job_title"],
                source=submitted["source"],
                source_url=submitted["source_url"],
                problem_opportunity=(
                    submitted[
                        "problem_opportunity"
                    ]
                ),
                why_mark_fits=(
                    submitted["why_mark_fits"]
                ),
                next_action=(
                    submitted["next_action"]
                ),
                next_action_due_date=(
                    submitted[
                        "next_action_due_date"
                    ]
                ),
                notes=submitted["notes"],
            )


def test_unrelated_sourcer_cannot_submit(
    submission_database,
):
    with database.get_db() as db:
        lead = _create_lead(db)

        with pytest.raises(
            LeadPermissionError,
            match="not allowed",
        ):
            submit_research_for_review(
                db,
                lead["id"],
                actor=OTHER_SOURCER,
            )

        unchanged = db.execute(
            """
            SELECT
                research_status,
                submitted_for_review_at
            FROM leads
            WHERE id = ?
            """,
            (lead["id"],),
        ).fetchone()
        assert (
            unchanged["research_status"]
            == "draft"
        )
        assert (
            unchanged[
                "submitted_for_review_at"
            ]
            is None
        )


def test_duplicate_submission_is_rejected(
    submission_database,
):
    with database.get_db() as db:
        lead = _create_lead(db)
        first = submit_research_for_review(
            db,
            lead["id"],
            actor=BROTHER,
        )

        with pytest.raises(
            LeadPermissionError,
            match="not allowed",
        ):
            submit_research_for_review(
                db,
                lead["id"],
                actor=BROTHER,
            )

        event_count = db.execute(
            """
            SELECT COUNT(*)
            FROM quest_updates
            WHERE task_id = ?
              AND event_type = (
                  'crm_research_submitted'
              )
            """,
            (first["quest_id"],),
        ).fetchone()[0]
        assert event_count == 1


def test_changes_requested_can_be_resubmitted(
    submission_database,
):
    with database.get_db() as db:
        lead = _create_lead(db)
        db.execute(
            """
            UPDATE leads
            SET
                research_status = (
                    'changes_requested'
                ),
                submitted_for_review_at = (
                    '2026-08-01 10:00:00'
                ),
                review_notes = (
                    'Verify the contact title.'
                )
            WHERE id = ?
            """,
            (lead["id"],),
        )

        resubmitted = submit_research_for_review(
            db,
            lead["id"],
            actor=BROTHER,
        )

        assert (
            resubmitted["research_status"]
            == "ready_for_review"
        )
        assert (
            resubmitted[
                "submitted_for_review_at"
            ]
            != "2026-08-01 10:00:00"
        )
        assert (
            resubmitted["review_notes"]
            == "Verify the contact title."
        )


def test_owner_queue_contains_only_pending_active_research(
    submission_database,
):
    with database.get_db() as db:
        first = _create_lead(
            db,
            company="First Review",
            priority="low",
        )
        second = _create_lead(
            db,
            company="Second Review",
            priority="high",
        )
        ignored = _create_lead(
            db,
            company="Still Draft",
        )

        submit_research_for_review(
            db,
            first["id"],
            actor=BROTHER,
        )
        submit_research_for_review(
            db,
            second["id"],
            actor=BROTHER,
        )

        db.execute(
            """
            UPDATE leads
            SET submitted_for_review_at = ?
            WHERE id = ?
            """,
            (
                "2026-08-05 10:00:00",
                first["id"],
            ),
        )
        db.execute(
            """
            UPDATE leads
            SET submitted_for_review_at = ?
            WHERE id = ?
            """,
            (
                "2026-08-05 11:00:00",
                second["id"],
            ),
        )

        queue = list_research_review_queue(db)

        assert [
            row["company"]
            for row in queue
        ] == [
            "First Review",
            "Second Review",
        ]
        assert all(
            row["research_status"]
            == "ready_for_review"
            for row in queue
        )
        assert ignored["company"] not in {
            row["company"]
            for row in queue
        }


def test_approved_state_cannot_be_submitted(
    submission_database,
):
    with database.get_db() as db:
        lead = _create_lead(db)
        db.execute(
            """
            UPDATE leads
            SET research_status = 'approved'
            WHERE id = ?
            """,
            (lead["id"],),
        )
        approved = db.execute(
            """
            SELECT *
            FROM leads
            WHERE id = ?
            """,
            (lead["id"],),
        ).fetchone()

        assert not can_submit_for_review(
            BROTHER,
            approved,
        )
        with pytest.raises(
            LeadPermissionError,
            match="not allowed",
        ):
            submit_research_for_review(
                db,
                lead["id"],
                actor=BROTHER,
            )
