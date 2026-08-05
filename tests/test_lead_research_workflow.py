from __future__ import annotations

import sqlite3

import pytest

from app import database
from app.services.lead_research_permissions import (
    LeadPermissionError,
)
from app.services.lead_research_workflow import (
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
def research_database(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "research-edit.db"
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
        owner = db.execute(
            """
            SELECT id
            FROM users
            WHERE role = 'owner'
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        assert owner["id"] == OWNER["id"]

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
                VALUES (?, ?, ?, ?, 'lead_sourcer', 1, 0)
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


def _create_brother_lead(db):
    return create_lead(
        db,
        company="Draft Analytics",
        contact_person="Dana Buyer",
        job_title="Founder",
        source="LinkedIn",
        source_url=(
            "https://example.com/draft-analytics"
        ),
        problem_opportunity=(
            "Reporting is manual."
        ),
        why_mark_fits=(
            "Mark can automate reporting."
        ),
        pipeline_status="new",
        priority="medium",
        next_action="Complete research.",
        next_action_due_date="2026-08-10",
        notes="Initial note.",
        created_by_user_id=BROTHER["id"],
        assigned_to_user_id=OWNER["id"],
    ).lead


def test_brother_can_save_related_draft_research(
    research_database,
):
    with database.get_db() as db:
        lead = _create_brother_lead(db)

        updated = update_research_details(
            db,
            lead["id"],
            actor=BROTHER,
            company="Draft Analytics Studio",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="LinkedIn",
            source_url=(
                "https://example.com/draft-analytics"
            ),
            problem_opportunity=(
                "Weekly reporting takes eight hours."
            ),
            why_mark_fits=(
                "Mark has Power BI and automation "
                "experience."
            ),
            next_action=(
                "Prepare the lead for Owner review."
            ),
            next_action_due_date="2026-08-11",
            notes="Research verified.",
        )

        assert (
            updated["company"]
            == "Draft Analytics Studio"
        )
        assert (
            updated["research_status"]
            == "researching"
        )
        assert (
            updated["researched_by_user_id"]
            == BROTHER["id"]
        )
        assert updated["pipeline_status"] == "new"
        assert updated["priority"] == "medium"
        assert updated["reviewed_by_user_id"] is None
        assert (
            updated[
                "outreach_approved_by_user_id"
            ]
            is None
        )

        quest = db.execute(
            """
            SELECT title, description, due_date
            FROM tasks
            WHERE id = ?
            """,
            (updated["quest_id"],),
        ).fetchone()
        assert "Draft Analytics Studio" in (
            quest["title"]
        )
        assert quest["due_date"] == "2026-08-11"

        event = db.execute(
            """
            SELECT event_type
            FROM quest_updates
            WHERE task_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (updated["quest_id"],),
        ).fetchone()
        assert (
            event["event_type"]
            == "crm_research_saved"
        )


def test_unrelated_sourcer_cannot_edit_research(
    research_database,
):
    with database.get_db() as db:
        lead = _create_brother_lead(db)

        with pytest.raises(
            LeadPermissionError,
            match="not allowed",
        ):
            update_research_details(
                db,
                lead["id"],
                actor=OTHER_SOURCER,
                company=lead["company"],
                contact_person=(
                    lead["contact_person"]
                ),
                job_title=lead["job_title"],
                source=lead["source"],
                source_url=lead["source_url"],
                problem_opportunity=(
                    lead["problem_opportunity"]
                ),
                why_mark_fits=(
                    lead["why_mark_fits"]
                ),
                next_action=lead["next_action"],
                next_action_due_date=(
                    lead["next_action_due_date"]
                ),
                notes=lead["notes"],
            )


def test_approved_lead_is_read_only_to_sourcer(
    research_database,
):
    with database.get_db() as db:
        lead = _create_brother_lead(db)
        db.execute(
            """
            UPDATE leads
            SET research_status = 'approved'
            WHERE id = ?
            """,
            (lead["id"],),
        )

        with pytest.raises(
            LeadPermissionError,
            match="not allowed",
        ):
            update_research_details(
                db,
                lead["id"],
                actor=BROTHER,
                company=lead["company"],
                contact_person=(
                    lead["contact_person"]
                ),
                job_title=lead["job_title"],
                source=lead["source"],
                source_url=lead["source_url"],
                problem_opportunity=(
                    lead["problem_opportunity"]
                ),
                why_mark_fits=(
                    lead["why_mark_fits"]
                ),
                next_action=lead["next_action"],
                next_action_due_date=(
                    lead["next_action_due_date"]
                ),
                notes=lead["notes"],
            )


def test_failed_duplicate_edit_rolls_back_research_metadata(
    research_database,
):
    with database.get_db() as db:
        first = _create_brother_lead(db)
        second = create_lead(
            db,
            company="Second Company",
            contact_person="Second Buyer",
            source="LinkedIn",
            problem_opportunity="Needs automation.",
            why_mark_fits="Mark fits.",
            next_action="Research.",
            created_by_user_id=BROTHER["id"],
            assigned_to_user_id=OWNER["id"],
        ).lead

        with pytest.raises(
            ValueError,
            match="already has this identity",
        ):
            update_research_details(
                db,
                first["id"],
                actor=BROTHER,
                company=second["company"],
                contact_person=(
                    second["contact_person"]
                ),
                job_title=second["job_title"],
                source=second["source"],
                source_url=second["source_url"],
                problem_opportunity=(
                    first["problem_opportunity"]
                ),
                why_mark_fits=(
                    first["why_mark_fits"]
                ),
                next_action=first["next_action"],
                next_action_due_date=(
                    first["next_action_due_date"]
                ),
                notes=first["notes"],
            )

        unchanged = db.execute(
            """
            SELECT
                company,
                research_status,
                researched_by_user_id
            FROM leads
            WHERE id = ?
            """,
            (first["id"],),
        ).fetchone()

        assert unchanged["company"] == (
            "Draft Analytics"
        )
        assert (
            unchanged["research_status"]
            == "draft"
        )
        assert (
            unchanged["researched_by_user_id"]
            is None
        )

        assert db.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []
