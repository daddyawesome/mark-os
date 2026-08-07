from __future__ import annotations

import asyncio

import pytest
from fastapi import Request
from fastapi.responses import PlainTextResponse

from app import auth, database
import app.main as main_module
from app.routes.workspaces import select_workspace
from app.services.access_control import landing_path_for_user
from app.services.team_users import (
    change_own_password,
    create_lead_sourcer,
    create_relationship_manager,
    reset_user_password,
)
from app.services.users import authenticate_user
from app.services.workspace_context import (
    SESSION_CURRENT_ORGANIZATION_ID_KEY,
    workspace_display_role,
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _request(
    path: str,
    *,
    method: str = "GET",
    session: dict | None = None,
    state: dict | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "session": session if session is not None else {},
            "state": state if state is not None else {},
        }
    )


def test_workspace_display_labels_match_pendang_launch_roles():
    owner = {
        "role": "owner",
        "current_workspace": {
            "slug": "pendang",
            "membership_role": "workspace_admin",
        },
    }
    rey = {
        "role": "relationship_manager",
        "current_workspace": {
            "slug": "pendang",
            "membership_role": "workspace_owner",
        },
    }
    freddy = {
        "role": "lead_sourcer",
        "current_workspace": {
            "slug": "pendang",
            "membership_role": "crm_contributor",
        },
    }

    assert workspace_display_role(owner) == "Pendang Administrator"
    assert (
        workspace_display_role(rey)
        == "Pendang Workspace Owner / Managing Director"
    )
    assert workspace_display_role(freddy) == "Pendang Lead Researcher"
    assert landing_path_for_user(rey) == "/crm"
    assert landing_path_for_user(freddy) == "/crm"


def test_owner_workspace_switch_route_selects_only_authorized_workspace(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "workspace-switch-ui.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        authenticated = authenticate_user(db, "mark", "owner-password")
        pendang_id = int(
            db.execute(
                "SELECT id FROM organizations WHERE slug = 'pendang'"
            ).fetchone()["id"]
        )
        foreign_id = int(
            db.execute(
                "INSERT INTO organizations (slug, name) VALUES (?, ?)",
                ("foreign", "Foreign"),
            ).lastrowid
        )

    session: dict = {}
    sign_in_request = _request("/crm", session=session)
    auth.sign_in(sign_in_request, authenticated)
    owner = auth.current_user(sign_in_request)
    assert owner["current_workspace"]["slug"] == "mark-agency"

    request = _request(
        "/workspace/select",
        method="POST",
        session=session,
        state={"current_user": owner},
    )
    response = select_workspace(
        request,
        organization_id=pendang_id,
        next="/crm/follow-ups",
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/crm/follow-ups"
    assert session[SESSION_CURRENT_ORGANIZATION_ID_KEY] == pendang_id

    denied = select_workspace(
        request,
        organization_id=foreign_id,
        next="https://example.com/steal",
    )
    assert denied.status_code == 403
    assert session[SESSION_CURRENT_ORGANIZATION_ID_KEY] == pendang_id


def test_single_workspace_staff_cannot_use_owner_switch_route(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "staff-switch-denied.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        staff = create_lead_sourcer(
            db,
            username="freddy",
            display_name="Freddy",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
            workspace_slug="pendang",
        )
        pendang_id = int(
            db.execute(
                "SELECT id FROM organizations WHERE slug = 'pendang'"
            ).fetchone()["id"]
        )

    request = _request(
        "/workspace/select",
        method="POST",
        state={"current_user": staff},
    )
    response = select_workspace(
        request,
        organization_id=pendang_id,
        next="/crm",
    )
    assert response.status_code == 403


def test_managed_accounts_and_admin_resets_use_temporary_passwords(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "temporary-passwords.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        rey = create_relationship_manager(
            db,
            username="rey",
            display_name="Rey",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
            workspace_slug="pendang",
            membership_role="workspace_owner",
        )
        assert rey["must_change_password"] == 1

        changed = change_own_password(
            db,
            user_id=int(rey["id"]),
            current_password="temporary-pass-123",
            password="rey-private-pass-456",
            password_confirmation="rey-private-pass-456",
        )
        assert changed["must_change_password"] == 0
        assert changed["session_version"] == rey["session_version"] + 1
        assert authenticate_user(db, "rey", "temporary-pass-123") is None
        assert authenticate_user(db, "rey", "rey-private-pass-456") is not None

        reset = reset_user_password(
            db,
            target_user_id=int(rey["id"]),
            password="new-temporary-pass-789",
            password_confirmation="new-temporary-pass-789",
        )
        assert reset["must_change_password"] == 1
        assert reset["session_version"] == changed["session_version"] + 1


def test_change_own_password_rejects_wrong_or_reused_current_password(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "password-change-validation.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        staff = create_lead_sourcer(
            db,
            username="researcher",
            display_name="Researcher",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
            workspace_slug="pendang",
        )

        with pytest.raises(ValueError, match="Current password is incorrect"):
            change_own_password(
                db,
                user_id=int(staff["id"]),
                current_password="wrong-password",
                password="private-password-456",
                password_confirmation="private-password-456",
            )

        with pytest.raises(ValueError, match="differs from the current"):
            change_own_password(
                db,
                user_id=int(staff["id"]),
                current_password="temporary-pass-123",
                password="temporary-pass-123",
                password_confirmation="temporary-pass-123",
            )


def test_password_change_gate_blocks_other_pages_until_temp_password_replaced(
    monkeypatch,
):
    temp_user = {
        "id": 12,
        "username": "freddy",
        "display_name": "Freddy",
        "role": "lead_sourcer",
        "must_change_password": 1,
        "current_workspace": {
            "id": 2,
            "slug": "pendang",
            "name": "Pendang Research & Analytics",
            "membership_role": "crm_contributor",
        },
        "authorized_workspaces": [],
    }
    monkeypatch.setattr(main_module, "current_user", lambda request: temp_user)

    async def call_next(request):
        return PlainTextResponse("allowed")

    crm_response = asyncio.run(
        main_module.login_and_permission_guard(
            _request("/crm"),
            call_next,
        )
    )
    assert crm_response.status_code == 303
    assert crm_response.headers["location"] == "/account/password"

    blocked_post = asyncio.run(
        main_module.login_and_permission_guard(
            _request("/crm/leads", method="POST"),
            call_next,
        )
    )
    assert blocked_post.status_code == 403
    assert blocked_post.body == b"Forbidden"

    password_page = asyncio.run(
        main_module.login_and_permission_guard(
            _request("/account/password"),
            call_next,
        )
    )
    assert password_page.status_code == 200


def test_forest_fieldbook_shows_owner_selector_and_pendang_launch_presets():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    base = (root / "app/templates/base.html").read_text(encoding="utf-8")
    crm = (root / "app/templates/client_hunting.html").read_text(encoding="utf-8")
    user_new = (root / "app/templates/user_new.html").read_text(encoding="utf-8")
    password = (root / "app/templates/account_password.html").read_text(encoding="utf-8")

    assert 'action="/workspace/select"' in base
    assert "current_user.role == 'owner'" in base
    assert "authorized_workspaces|length > 1" in base
    assert "current_user.workspace_display_role" in base
    assert "Pendang Research &amp; Analytics" in crm
    assert "Pendang Workspace Owner / Managing Director" in user_new
    assert "Pendang Lead Researcher" in user_new
    assert "must replace it at first sign-in" in user_new
    assert 'action="/account/password"' in password
