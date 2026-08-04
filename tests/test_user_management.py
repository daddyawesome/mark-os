from __future__ import annotations

from app import database
from app.services.leads import create_lead
from app.services.team_users import (
    create_lead_sourcer,
    get_primary_owner_id,
    get_user_for_management,
    list_users_with_stats,
    reset_user_password,
    set_user_active,
)
from app.services.users import authenticate_user


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def test_user_management_lists_lead_counts(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "user-management.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db, active_only=True)
        sourcer = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        create_lead(
            db,
            company="Team Metrics Co",
            contact_person="Alex Buyer",
            source="LinkedIn",
            problem_opportunity="Needs reporting support",
            why_mark_fits="Mark builds Power BI systems",
            next_action="Review the lead",
            created_by_user_id=sourcer["id"],
            assigned_to_user_id=owner_id,
        )

        users = list_users_with_stats(db)

    by_username = {user["username"]: user for user in users}
    assert by_username["mark"]["role"] == "owner"
    assert by_username["brother"]["role"] == "lead_sourcer"
    assert by_username["brother"]["lead_count"] == 1
    assert by_username["brother"]["active_lead_count"] == 1


def test_deactivation_revokes_sessions_and_reassigns_leads(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "deactivate-user.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db, active_only=True)
        sourcer = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        result = create_lead(
            db,
            company="Reassign Analytics",
            contact_person="Jamie Client",
            source="Referral",
            problem_opportunity="Needs a dashboard",
            why_mark_fits="Mark has BI experience",
            next_action="Owner reviews the opportunity",
            created_by_user_id=sourcer["id"],
            assigned_to_user_id=sourcer["id"],
        )
        before_version = sourcer["session_version"]

        updated = set_user_active(
            db,
            target_user_id=sourcer["id"],
            acting_user_id=owner_id,
            active=False,
        )

        lead = db.execute(
            """
            SELECT created_by_user_id, assigned_to_user_id
            FROM leads
            WHERE id = ?
            """,
            (result.lead["id"],),
        ).fetchone()

    assert updated["active"] == 0
    assert updated["session_version"] == before_version + 1
    assert lead["created_by_user_id"] == sourcer["id"]
    assert lead["assigned_to_user_id"] == owner_id


def test_owner_cannot_be_deactivated(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "protect-owner.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db, active_only=True)

        try:
            set_user_active(
                db,
                target_user_id=owner_id,
                acting_user_id=owner_id,
                active=False,
            )
        except ValueError as exc:
            message = str(exc)
        else:
            raise AssertionError("Owner deactivation unexpectedly succeeded.")

        owner = get_user_for_management(db, owner_id)

    assert "Owner accounts cannot be deactivated" in message
    assert owner["active"] == 1


def test_password_reset_revokes_sessions_and_changes_credentials(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "reset-password.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        sourcer = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        before_version = sourcer["session_version"]

        updated = reset_user_password(
            db,
            target_user_id=sourcer["id"],
            password="replacement-pass-456",
            password_confirmation="replacement-pass-456",
        )

        old_login = authenticate_user(
            db,
            "brother",
            "temporary-pass-123",
        )
        new_login = authenticate_user(
            db,
            "brother",
            "replacement-pass-456",
        )

    assert updated["session_version"] == before_version + 1
    assert old_login is None
    assert new_login is not None
    assert new_login["id"] == sourcer["id"]
