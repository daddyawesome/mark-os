from __future__ import annotations

import sqlite3

import pytest

from app import database
from app.db import family_workspace
from app.services.access_control import (
    can_access_request,
    landing_path_for_user,
    permitted_destination,
)
from app.services.team_users import create_lead_sourcer, create_member


OWNER = {
    "id": 1,
    "username": "mark",
    "display_name": "Mark",
    "role": "owner",
}
MEMBER = {
    "id": 2,
    "username": "wife",
    "display_name": "Wife",
    "role": "member",
}
LEAD_SOURCER = {
    "id": 3,
    "username": "brother",
    "display_name": "Brother",
    "role": "lead_sourcer",
}

CONTENT_TABLES = (
    "goals",
    "projects",
    "checkins",
    "directions",
    "game_history",
    "tasks",
    "quest_updates",
    "xp_ledger",
    "memories",
    "memory_candidates",
    "memory_audit_events",
    "timeline_events",
    "chat_sessions",
    "chat_messages",
    "agent_runs",
    "agent_steps",
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _initialize(tmp_path, monkeypatch):
    database_path = tmp_path / "m10-family.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()
    return database_path


def test_member_receives_full_private_personal_surface():
    allowed = (
        ("GET", "/"),
        ("GET", "/quests"),
        ("GET", "/quests/1"),
        ("POST", "/quests"),
        ("POST", "/quests/1/start"),
        ("GET", "/goals"),
        ("POST", "/goals"),
        ("GET", "/life-os"),
        ("GET", "/history"),
        ("GET", "/history/1/edit"),
        ("POST", "/history/1/edit"),
        ("POST", "/history/1/delete"),
        ("POST", "/check-in"),
        ("POST", "/logout"),
    )
    denied = (
        ("GET", "/crm"),
        ("POST", "/crm/leads"),
        ("GET", "/settings/users"),
        ("GET", "/settings/users/new"),
    )

    assert all(
        can_access_request(MEMBER, method, path)
        for method, path in allowed
    )
    assert not any(
        can_access_request(MEMBER, method, path)
        for method, path in denied
    )
    assert landing_path_for_user(MEMBER) == "/"
    assert permitted_destination(MEMBER, "/quests") == "/quests"
    assert permitted_destination(MEMBER, "/crm") == "/"


def test_member_workspace_starts_blank_except_required_singletons(
    tmp_path,
    monkeypatch,
):
    _initialize(tmp_path, monkeypatch)

    with database.get_db() as db:
        member = create_member(
            db,
            username="wife",
            display_name="Wife",
            password="family-pass-123",
            password_confirmation="family-pass-123",
        )
        member_id = int(member["id"])

        assert db.execute(
            "SELECT COUNT(*) FROM profile WHERE user_id = ?",
            (member_id,),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM game_state WHERE user_id = ?",
            (member_id,),
        ).fetchone()[0] == 1

        for table_name in CONTENT_TABLES:
            assert db.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE user_id = ?",
                (member_id,),
            ).fetchone()[0] == 0


def test_workspace_creation_is_idempotent(tmp_path, monkeypatch):
    _initialize(tmp_path, monkeypatch)

    with database.get_db() as db:
        member = create_member(
            db,
            username="daughter",
            display_name="Daughter",
            password="family-pass-456",
            password_confirmation="family-pass-456",
        )
        member_id = int(member["id"])

        first = family_workspace.ensure_personal_workspace(db, member_id)
        second = family_workspace.ensure_personal_workspace(db, member_id)

        assert first.profile_created is False
        assert first.game_state_created is False
        assert second.profile_created is False
        assert second.game_state_created is False
        assert db.execute(
            "SELECT COUNT(*) FROM profile WHERE user_id = ?",
            (member_id,),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM game_state WHERE user_id = ?",
            (member_id,),
        ).fetchone()[0] == 1


def test_project_names_are_unique_per_user_not_globally(
    tmp_path,
    monkeypatch,
):
    _initialize(tmp_path, monkeypatch)

    with database.get_db() as db:
        owner_id = int(
            db.execute(
                "SELECT id FROM users WHERE role = 'owner'"
            ).fetchone()[0]
        )
        member = create_member(
            db,
            username="wife",
            display_name="Wife",
            password="family-pass-123",
            password_confirmation="family-pass-123",
        )
        member_id = int(member["id"])

        values = (
            "Shared Family Plan",
            "Private plan with a reusable display name.",
            "active",
            5,
            0,
            "Choose the first action.",
        )
        db.execute(
            """
            INSERT INTO projects (
                user_id, name, purpose, status,
                priority, progress, next_action
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (owner_id, *values),
        )
        db.execute(
            """
            INSERT INTO projects (
                user_id, name, purpose, status,
                priority, progress, next_action
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (member_id, *values),
        )

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """
                INSERT INTO projects (
                    user_id, name, purpose, status,
                    priority, progress, next_action
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (owner_id, *values),
            )


def test_memory_keys_are_unique_per_user_not_globally(
    tmp_path,
    monkeypatch,
):
    _initialize(tmp_path, monkeypatch)

    with database.get_db() as db:
        owner_id = int(
            db.execute(
                "SELECT id FROM users WHERE role = 'owner'"
            ).fetchone()[0]
        )
        member = create_member(
            db,
            username="wife",
            display_name="Wife",
            password="family-pass-123",
            password_confirmation="family-pass-123",
        )
        member_id = int(member["id"])

        values = (
            "preference",
            "favorite_focus",
            "Protect focused work time.",
            7,
            "m10_test",
        )
        db.execute(
            """
            INSERT INTO memories (
                user_id, memory_type, memory_key,
                memory_value, importance, source
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (owner_id, *values),
        )
        db.execute(
            """
            INSERT INTO memories (
                user_id, memory_type, memory_key,
                memory_value, importance, source
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (member_id, *values),
        )

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """
                INSERT INTO memories (
                    user_id, memory_type, memory_key,
                    memory_value, importance, source
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (owner_id, *values),
            )


def test_lead_sourcer_stays_crm_only_without_personal_workspace(
    tmp_path,
    monkeypatch,
):
    _initialize(tmp_path, monkeypatch)

    with database.get_db() as db:
        sourcer = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="sourcer-pass-123",
            password_confirmation="sourcer-pass-123",
        )
        sourcer_id = int(sourcer["id"])

        assert db.execute(
            "SELECT COUNT(*) FROM profile WHERE user_id = ?",
            (sourcer_id,),
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM game_state WHERE user_id = ?",
            (sourcer_id,),
        ).fetchone()[0] == 0

    assert can_access_request(LEAD_SOURCER, "GET", "/crm")
    assert can_access_request(LEAD_SOURCER, "POST", "/crm/leads")
    assert not can_access_request(LEAD_SOURCER, "GET", "/")
    assert not can_access_request(LEAD_SOURCER, "GET", "/quests")
    assert landing_path_for_user(LEAD_SOURCER) == "/crm"
