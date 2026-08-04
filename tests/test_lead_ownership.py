from __future__ import annotations

import sqlite3

import pytest

from app import database
from app.db import leads as lead_schema
from app.services.access_control import can_access_request
from app.services.leads import (
    create_lead,
    get_crm_dashboard_metrics,
    get_lead,
    list_leads,
)
from app.services.passwords import verify_password
from app.services.team_users import (
    create_lead_sourcer,
    get_primary_owner_id,
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def test_create_lead_sourcer_hashes_password_and_rejects_duplicates(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "team-user.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        user = create_lead_sourcer(
            db,
            username="brother",
            display_name="Mark's Brother",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        stored = db.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()

        with pytest.raises(ValueError, match="already in use"):
            create_lead_sourcer(
                db,
                username="BROTHER",
                display_name="Duplicate",
                password="another-pass-123",
                password_confirmation="another-pass-123",
            )

    assert user["role"] == "lead_sourcer"
    assert user["active"] == 1
    assert verify_password("temporary-pass-123", stored["password_hash"])
    assert "temporary-pass-123" not in stored["password_hash"]


def test_new_lead_records_creator_and_owner_assignment(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "lead-ownership.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db)
        sourcer = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        result = create_lead(
            db,
            company="Ownership Analytics",
            contact_person="Alex Buyer",
            source="LinkedIn",
            problem_opportunity="Needs a reliable sales dashboard",
            why_mark_fits="Mark builds Power BI and SQL systems",
            next_action="Review and contact the lead",
            priority="high",
            created_by_user_id=sourcer["id"],
            assigned_to_user_id=owner_id,
        )

        lead = get_lead(db, result.lead["id"])
        brother_leads = list_leads(
            db,
            created_by_user_id=sourcer["id"],
        )
        owner_created_leads = list_leads(
            db,
            created_by_user_id=owner_id,
        )
        brother_metrics = get_crm_dashboard_metrics(
            db,
            created_by_user_id=sourcer["id"],
        )

    assert lead["created_by_user_id"] == sourcer["id"]
    assert lead["assigned_to_user_id"] == owner_id
    assert lead["created_by_name"] == "Brother"
    assert lead["assigned_to_name"] == "Mark"
    assert [row["id"] for row in brother_leads] == [lead["id"]]
    assert owner_created_leads == []
    assert brother_metrics["total_leads"] == 1
    assert brother_metrics["high_priority_leads"] == 1


def test_existing_unattributed_lead_is_backfilled_to_owner(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "ownership-backfill.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db)
        quest_id = db.execute(
            """
            INSERT INTO tasks (
                title,
                description,
                status,
                quest_source,
                why
            )
            VALUES (
                'Historical lead',
                'Ownership migration fixture',
                'backlog',
                'client_hunting',
                'Confirm safe ownership backfill.'
            )
            """
        ).lastrowid
        lead_id = db.execute(
            """
            INSERT INTO leads (
                quest_id,
                request_fingerprint,
                dedupe_key,
                company,
                contact_person,
                source,
                problem_opportunity,
                why_mark_fits,
                next_action
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                quest_id,
                "historical-request-fingerprint",
                "historical-dedupe-key",
                "Historical Client",
                "Jamie Contact",
                "Referral",
                "Needs data help",
                "Mark can deliver",
                "Review historical lead",
            ),
        ).lastrowid

        before = db.execute(
            """
            SELECT created_by_user_id, assigned_to_user_id
            FROM leads
            WHERE id = ?
            """,
            (lead_id,),
        ).fetchone()
        assert before["created_by_user_id"] is None
        assert before["assigned_to_user_id"] is None

        lead_schema.migrate_ownership(db)

        after = db.execute(
            """
            SELECT created_by_user_id, assigned_to_user_id
            FROM leads
            WHERE id = ?
            """,
            (lead_id,),
        ).fetchone()

    assert after["created_by_user_id"] == owner_id
    assert after["assigned_to_user_id"] == owner_id


def test_lead_sourcer_cannot_open_team_account_page():
    owner = {"id": 1, "role": "owner"}
    sourcer = {"id": 2, "role": "lead_sourcer"}

    assert can_access_request(owner, "GET", "/settings/users/new")
    assert can_access_request(owner, "POST", "/settings/users/new")
    assert not can_access_request(sourcer, "GET", "/settings/users/new")
    assert not can_access_request(sourcer, "POST", "/settings/users/new")
