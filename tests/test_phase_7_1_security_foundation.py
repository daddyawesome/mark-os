from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import auth, database
from app.services.access_control import can_access_request
from app.services.account_security import (
    LOGIN_FAILURE_LIMIT,
    create_session,
    is_login_rate_limited,
    list_active_sessions,
    login_identifier,
    record_failed_login,
    revoke_all_sessions,
    validate_session,
)
from app.services.team_users import create_lead_sourcer, get_primary_owner_id, set_user_active
from app.services.users import authenticate_user


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def test_login_limit_uses_hashed_identifier_and_exact_window(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "rate-limit.db")
    _configure_owner(monkeypatch)
    database.init_db()
    now = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)
    identifier = login_identifier("test-secret", "Mark", "127.0.0.1")

    with database.get_db() as db:
        for _ in range(LOGIN_FAILURE_LIMIT):
            record_failed_login(db, identifier, now=now)
        assert is_login_rate_limited(db, identifier, now=now)
        assert not is_login_rate_limited(
            db, identifier, now=now + timedelta(minutes=15, seconds=1)
        )
        stored = db.execute("SELECT identifier_hash FROM login_attempts LIMIT 1").fetchone()
        audit = db.execute(
            "SELECT details_json FROM security_audit_events WHERE event_type = 'authentication_failed' LIMIT 1"
        ).fetchone()

    assert stored["identifier_hash"] == identifier
    assert "mark" not in stored["identifier_hash"]
    assert audit["details_json"] == "{}"


def test_session_inventory_and_logout_everywhere_preserve_current_session(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "sessions.db")
    _configure_owner(monkeypatch)
    database.init_db()
    with database.get_db() as db:
        user = authenticate_user(db, "mark", "owner-password-123")
        first = create_session(
            db, user_id=user["id"], session_version=user["session_version"]
        )
        second = create_session(
            db, user_id=user["id"], session_version=user["session_version"]
        )
        first_id = validate_session(
            db,
            token=first,
            user_id=user["id"],
            session_version=user["session_version"],
        )
        sessions = list_active_sessions(
            db, user_id=user["id"], current_session_id=first_id
        )
        before_game = db.execute(
            "SELECT level, xp_total, xp_into_level FROM game_state WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
        assert len(sessions) == 2
        assert sum(session["is_current"] for session in sessions) == 1
        assert revoke_all_sessions(
            db, user_id=user["id"], except_session_id=first_id
        ) == 1
        assert validate_session(
            db,
            token=first,
            user_id=user["id"],
            session_version=user["session_version"],
        ) == first_id
        assert validate_session(
            db,
            token=second,
            user_id=user["id"],
            session_version=user["session_version"],
        ) is None
        after_game = db.execute(
            "SELECT level, xp_total, xp_into_level FROM game_state WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
    assert tuple(before_game) == tuple(after_game)


def test_admin_account_change_is_owner_enforced_and_audited(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "audit.db")
    _configure_owner(monkeypatch)
    database.init_db()
    with database.get_db() as db:
        owner_id = get_primary_owner_id(db, active_only=True)
        sourcer = create_lead_sourcer(
            db,
            username="researcher",
            display_name="Researcher",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        try:
            set_user_active(
                db,
                target_user_id=sourcer["id"],
                acting_user_id=sourcer["id"],
                active=False,
            )
        except ValueError as exc:
            assert "Owner" in str(exc)
        else:
            raise AssertionError("Non-owner account change unexpectedly succeeded")

        set_user_active(
            db,
            target_user_id=sourcer["id"],
            acting_user_id=owner_id,
            active=False,
        )
        event = db.execute(
            """
            SELECT event_type, actor_user_id, target_user_id
            FROM security_audit_events
            WHERE event_type = 'account_deactivated'
            """
        ).fetchone()
    assert tuple(event) == ("account_deactivated", owner_id, sourcer["id"])


def test_security_routes_are_not_idor_accessible_to_staff():
    staff = {"id": 2, "role": "lead_sourcer"}
    assert can_access_request(staff, "GET", "/account/sessions")
    assert not can_access_request(
        staff, "GET", "/settings/users/security-audit/events"
    )
    assert not can_access_request(staff, "POST", "/settings/users/1/status")


def test_database_role_change_is_always_audited(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "role-audit.db")
    _configure_owner(monkeypatch)
    database.init_db()
    with database.get_db() as db:
        sourcer = create_lead_sourcer(
            db,
            username="role-change",
            display_name="Role Change",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        db.execute(
            "UPDATE users SET role = 'relationship_manager' WHERE id = ?",
            (sourcer["id"],),
        )
        event = db.execute(
            """
            SELECT event_type, target_user_id, details_json
            FROM security_audit_events
            WHERE event_type = 'role_changed' AND target_user_id = ?
            """,
            (sourcer["id"],),
        ).fetchone()
    assert event["event_type"] == "role_changed"
    assert event["target_user_id"] == sourcer["id"]
    assert event["details_json"] == '{"from":"lead_sourcer","to":"relationship_manager"}'
