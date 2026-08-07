from __future__ import annotations

import asyncio

import pytest
from fastapi import Request
from fastapi.responses import PlainTextResponse

from app import auth, database
import app.main as main_module
from app.services.users import authenticate_user
from app.services.workspace_context import (
    SESSION_CURRENT_ORGANIZATION_ID_KEY,
    select_current_workspace,
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _request_with_session(session: dict | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/crm",
            "raw_path": b"/crm",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "session": session or {},
        }
    )


def test_owner_memberships_are_seeded_idempotently(tmp_path, monkeypatch):
    database_path = tmp_path / "workspace-memberships.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner = db.execute(
            "SELECT id, role FROM users WHERE username = 'mark'"
        ).fetchone()
        memberships_before = db.execute(
            """
            SELECT o.slug, m.membership_role, m.created_at
            FROM organization_memberships AS m
            JOIN organizations AS o ON o.id = m.organization_id
            WHERE m.user_id = ?
            ORDER BY o.slug
            """,
            (owner["id"],),
        ).fetchall()

    database.init_db()

    with database.get_db() as db:
        memberships_after = db.execute(
            """
            SELECT o.slug, m.membership_role, m.created_at
            FROM organization_memberships AS m
            JOIN organizations AS o ON o.id = m.organization_id
            WHERE m.user_id = ?
            ORDER BY o.slug
            """,
            (owner["id"],),
        ).fetchall()
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    assert owner["role"] == "owner"
    assert [(row["slug"], row["membership_role"]) for row in memberships_before] == [
        ("mark-agency", "workspace_admin"),
        ("pendang", "workspace_admin"),
    ]
    assert [tuple(row) for row in memberships_after] == [
        tuple(row) for row in memberships_before
    ]


def test_owner_session_defaults_to_mark_agency_and_lists_authorized_workspaces(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "workspace-session.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        user = authenticate_user(db, "mark", "owner-password")

    request = _request_with_session()
    auth.sign_in(request, user)
    resolved = auth.current_user(request)

    assert resolved is not None
    assert resolved["current_workspace"]["slug"] == "mark-agency"
    assert resolved["current_workspace"]["membership_role"] == "workspace_admin"
    assert [workspace["slug"] for workspace in resolved["authorized_workspaces"]] == [
        "mark-agency",
        "pendang",
    ]
    assert request.session[SESSION_CURRENT_ORGANIZATION_ID_KEY] == resolved[
        "current_workspace"
    ]["id"]


def test_owner_can_select_pendang_and_stale_selection_falls_back_safely(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "workspace-switch-foundation.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        user = authenticate_user(db, "mark", "owner-password")
        pendang_id = db.execute(
            "SELECT id FROM organizations WHERE slug = 'pendang'"
        ).fetchone()["id"]
        unauthorized_id = db.execute(
            "INSERT INTO organizations (slug, name) VALUES (?, ?)",
            ("not-authorized", "Not Authorized"),
        ).lastrowid

    request = _request_with_session()
    auth.sign_in(request, user)
    assert auth.current_user(request)["current_workspace"]["slug"] == "mark-agency"

    with database.get_db() as db:
        selected = select_current_workspace(
            db,
            request.session,
            user,
            pendang_id,
        )
    assert selected["slug"] == "pendang"
    assert auth.current_user(request)["current_workspace"]["slug"] == "pendang"

    current_selection = request.session[SESSION_CURRENT_ORGANIZATION_ID_KEY]
    with database.get_db() as db:
        with pytest.raises(PermissionError):
            select_current_workspace(
                db,
                request.session,
                user,
                unauthorized_id,
            )
    assert request.session[SESSION_CURRENT_ORGANIZATION_ID_KEY] == current_selection

    request.session[SESSION_CURRENT_ORGANIZATION_ID_KEY] = unauthorized_id
    assert auth.current_user(request)["current_workspace"]["slug"] == "mark-agency"


def test_middleware_exposes_resolved_workspace_without_enforcing_scope(monkeypatch):
    workspace = {
        "id": 2,
        "slug": "pendang",
        "name": "Pendang Research & Analytics",
        "membership_role": "crm_contributor",
    }
    user = {
        "id": 2,
        "username": "researcher",
        "display_name": "Researcher",
        "role": "lead_sourcer",
        "current_workspace": workspace,
        "authorized_workspaces": [workspace],
    }
    monkeypatch.setattr(main_module, "current_user", lambda request: user)
    observed = {}

    async def call_next(request):
        observed["workspace"] = request.state.current_workspace
        observed["authorized"] = request.state.authorized_workspaces
        return PlainTextResponse("allowed")

    response = asyncio.run(
        main_module.login_and_permission_guard(
            _request_with_session(),
            call_next,
        )
    )

    assert response.status_code == 200
    assert observed["workspace"] == workspace
    assert observed["authorized"] == [workspace]
