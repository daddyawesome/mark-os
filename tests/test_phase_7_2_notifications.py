from __future__ import annotations

from datetime import date

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.access_control import can_access_request
from app.services.leads import create_lead
from app.services.notifications import build_notifications
from app.services.team_users import create_lead_sourcer, get_primary_owner_id


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _actor(user, organization_id):
    return {
        **dict(user),
        "current_workspace": {
            "id": organization_id,
            "slug": "mark-agency",
            "membership_role": "crm_contributor",
        },
    }


def test_personal_nudges_are_user_scoped_and_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "personal-nudges.db")
    _configure_owner(monkeypatch)
    database.init_db()
    with database.get_db() as db:
        owner_id = get_primary_owner_id(db, active_only=True)
        owner = db.execute("SELECT id, role FROM users WHERE id = ?", (owner_id,)).fetchone()
        db.execute(
            """
            INSERT INTO tasks (user_id, title, due_date, status)
            VALUES (?, 'Owner overdue quest', '2026-09-01', 'active')
            """,
            (owner_id,),
        )
        game_before = [tuple(row) for row in db.execute("SELECT * FROM game_state ORDER BY id")]
        quest_before = [tuple(row) for row in db.execute("SELECT * FROM tasks ORDER BY id")]
        notifications = build_notifications(db, dict(owner), today=date(2026, 9, 7))
        game_after = [tuple(row) for row in db.execute("SELECT * FROM game_state ORDER BY id")]
        quest_after = [tuple(row) for row in db.execute("SELECT * FROM tasks ORDER BY id")]

    kinds = [item["kind"] for item in notifications]
    assert "checkin_reminder" in kinds
    assert "overdue_quest" in kinds
    assert "weekly_review_reminder" in kinds
    assert game_after == game_before
    assert quest_after == quest_before


def test_crm_due_nudges_do_not_leak_another_researchers_lead(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "crm-nudges.db")
    _configure_owner(monkeypatch)
    database.init_db()
    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        first = create_lead_sourcer(
            db,
            username="first",
            display_name="First",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        second = create_lead_sourcer(
            db,
            username="second",
            display_name="Second",
            password="temporary-pass-456",
            password_confirmation="temporary-pass-456",
        )
        for creator, company in ((first, "Visible Co"), (second, "Private Co")):
            create_lead(
                db,
                company=company,
                contact_person="Buyer",
                source="Referral",
                problem_opportunity="Needs reporting",
                why_mark_fits="MARK OS can help",
                next_action="Follow up",
                next_action_due_date="2026-09-03",
                created_by_user_id=creator["id"],
                assigned_to_user_id=creator["id"],
                organization_id=organization_id,
            )
        notifications = build_notifications(
            db, _actor(first, organization_id), today=date(2026, 9, 3)
        )

    text = " ".join(str(value) for item in notifications for value in item.values())
    assert "Visible Co" in text
    assert "Private Co" not in text


def test_notification_center_is_available_to_each_authenticated_role():
    for role in ("owner", "member", "lead_sourcer", "relationship_manager"):
        assert can_access_request({"id": 1, "role": role}, "GET", "/notifications")
