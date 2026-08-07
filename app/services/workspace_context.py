from __future__ import annotations

import sqlite3
from collections.abc import Mapping, MutableMapping
from typing import Any

from fastapi import Request

from app.db.organizations import (
    ensure_owner_workspace_memberships,
    organization_id_by_slug,
)


SESSION_CURRENT_ORGANIZATION_ID_KEY = "mark_os_current_organization_id"


def _positive_id(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive integer.")
    return parsed


def authorized_workspaces(
    db: sqlite3.Connection,
    user_id: int,
) -> list[dict[str, Any]]:
    safe_user_id = _positive_id(user_id, label="User ID")
    rows = db.execute(
        """
        SELECT
            o.id,
            o.slug,
            o.name,
            m.membership_role
        FROM organization_memberships AS m
        JOIN organizations AS o
          ON o.id = m.organization_id
        WHERE m.user_id = ?
          AND m.active = 1
        ORDER BY
            CASE WHEN o.slug = 'mark-agency' THEN 0 ELSE 1 END,
            o.name COLLATE NOCASE,
            o.id
        """,
        (safe_user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_workspace_session(
    db: sqlite3.Connection,
    session: MutableMapping[str, Any],
    user: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Resolve the signed-session workspace only from authorized memberships.

    Phase 6.6B-3 establishes request/session context without enforcing CRM
    organization filtering yet. Owners default to MARK Agency. A non-owner with
    exactly one membership defaults to that workspace. Users with no membership
    remain authenticated but unscoped until their explicit workspace membership
    is introduced by a later 6.6B staff step.
    """
    user_id = _positive_id(user.get("id"), label="User ID")
    role = str(user.get("role") or "").strip().casefold()
    if role == "owner":
        # New global owner records must never be stranded without the two
        # canonical workspace-admin memberships. This is idempotent.
        ensure_owner_workspace_memberships(db)

    workspaces = authorized_workspaces(db, user_id)
    by_id = {int(workspace["id"]): workspace for workspace in workspaces}

    raw_selected = session.get(SESSION_CURRENT_ORGANIZATION_ID_KEY)
    selected_id: int | None = None
    try:
        if raw_selected is not None:
            selected_id = _positive_id(
                raw_selected,
                label="Organization ID",
            )
    except ValueError:
        selected_id = None

    if selected_id is not None and selected_id in by_id:
        return by_id[selected_id], workspaces

    session.pop(SESSION_CURRENT_ORGANIZATION_ID_KEY, None)

    default_workspace: dict[str, Any] | None = None

    if role == "owner":
        default_workspace = next(
            (
                workspace
                for workspace in workspaces
                if workspace["slug"].casefold() == "mark-agency"
            ),
            None,
        )
    elif len(workspaces) == 1:
        default_workspace = workspaces[0]

    if default_workspace is not None:
        session[SESSION_CURRENT_ORGANIZATION_ID_KEY] = int(
            default_workspace["id"]
        )

    return default_workspace, workspaces


def select_current_workspace(
    db: sqlite3.Connection,
    session: MutableMapping[str, Any],
    user: Mapping[str, Any],
    organization_id: int,
) -> dict[str, Any]:
    """Persist a workspace selection only when the user is a member."""
    user_id = _positive_id(user.get("id"), label="User ID")
    safe_organization_id = _positive_id(
        organization_id,
        label="Organization ID",
    )
    workspace = db.execute(
        """
        SELECT
            o.id,
            o.slug,
            o.name,
            m.membership_role
        FROM organization_memberships AS m
        JOIN organizations AS o
          ON o.id = m.organization_id
        WHERE m.user_id = ? AND m.organization_id = ?
          AND m.active = 1
        """,
        (user_id, safe_organization_id),
    ).fetchone()
    if workspace is None:
        raise PermissionError("Workspace is not authorized for this user.")

    session[SESSION_CURRENT_ORGANIZATION_ID_KEY] = safe_organization_id
    return dict(workspace)



def require_workspace_membership(
    db: sqlite3.Connection,
    user_id: int,
    organization_id: int,
) -> dict[str, Any]:
    """Return one membership or fail without exposing other workspace data."""
    safe_user_id = _positive_id(user_id, label="User ID")
    safe_organization_id = _positive_id(
        organization_id,
        label="Organization ID",
    )
    row = db.execute(
        """
        SELECT
            o.id,
            o.slug,
            o.name,
            m.membership_role
        FROM organization_memberships AS m
        JOIN organizations AS o
          ON o.id = m.organization_id
        JOIN users AS u
          ON u.id = m.user_id
        WHERE m.user_id = ?
          AND m.organization_id = ?
          AND m.active = 1
          AND u.active = 1
        """,
        (safe_user_id, safe_organization_id),
    ).fetchone()
    if row is None:
        raise PermissionError("Workspace is not authorized for this user.")
    return dict(row)


def workspace_membership_role(user: Mapping[str, Any] | None) -> str:
    """Return the authenticated active-workspace role without widening global role."""
    if user is None:
        return ""
    direct = str(user.get("workspace_membership_role") or "").strip().casefold()
    if direct:
        return direct
    workspace = user.get("current_workspace")
    if isinstance(workspace, Mapping):
        return str(workspace.get("membership_role") or "").strip().casefold()
    return ""


def load_crm_actor_for_workspace(
    db: sqlite3.Connection,
    user: Mapping[str, Any],
    organization_id: int,
) -> dict[str, Any]:
    """Reload global role and active workspace membership from database truth."""
    safe_user_id = _positive_id(user.get("id"), label="User ID")
    safe_organization_id = _positive_id(
        organization_id,
        label="Organization ID",
    )
    membership = require_workspace_membership(
        db,
        safe_user_id,
        safe_organization_id,
    )
    row = db.execute(
        """
        SELECT id, username, display_name, role, active, must_change_password,
               session_version
        FROM users
        WHERE id = ? AND active = 1
        """,
        (safe_user_id,),
    ).fetchone()
    if row is None:
        raise PermissionError("Workspace is not authorized for this user.")
    actor = dict(row)
    actor["workspace_membership_role"] = membership["membership_role"]
    actor["current_workspace"] = dict(membership)
    return actor


def workspace_display_role(user: Mapping[str, Any] | None) -> str:
    """Return a clear UI label for the active workspace authority."""
    if user is None:
        return ""

    global_role = str(user.get("role") or "").strip().casefold()
    workspace = user.get("current_workspace")
    if not isinstance(workspace, Mapping):
        return global_role.replace("_", " ").title()

    slug = str(workspace.get("slug") or "").strip().casefold()
    membership_role = str(
        workspace.get("membership_role") or ""
    ).strip().casefold()

    if slug == "pendang":
        if global_role == "owner":
            return "Pendang Administrator"
        if (
            global_role == "relationship_manager"
            and membership_role == "workspace_owner"
        ):
            return "Pendang Workspace Owner / Managing Director"
        if global_role == "lead_sourcer":
            return "Pendang Lead Researcher"
        if global_role == "relationship_manager":
            return "Pendang Relationship Manager"

    if slug == "mark-agency":
        if global_role == "owner":
            return "MARK Agency Administrator"
        if global_role == "lead_sourcer":
            return "MARK Agency Lead Researcher"
        if global_role == "relationship_manager":
            return "Business Development Collaborator / Relationship Manager"

    if membership_role:
        return membership_role.replace("_", " ").title()
    return global_role.replace("_", " ").title()

def request_current_workspace(request: Request) -> dict[str, Any] | None:
    workspace = getattr(request.state, "current_workspace", None)
    return workspace if isinstance(workspace, dict) else None


def require_request_organization_id(
    request: Request,
    *,
    db: sqlite3.Connection | None = None,
) -> int:
    """Return the authenticated CRM workspace for a real request.

    Production middleware always installs ``current_workspace`` in request
    state. Older unit tests sometimes call route functions directly with a
    lightweight request object; only those calls may fall back to MARK Agency.
    An explicitly present ``None`` workspace fails closed.
    """
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict):
        state = scope.get("state", {})
        has_workspace_key = "current_workspace" in state
    else:
        request_state = getattr(request, "state", None)
        has_workspace_key = (
            request_state is not None
            and hasattr(request_state, "current_workspace")
        )

    if not has_workspace_key:
        if db is None:
            raise RuntimeError("Current workspace context is unavailable.")
        return organization_id_by_slug(db, "mark-agency")

    workspace = request_current_workspace(request)
    if workspace is None:
        raise PermissionError("An authorized CRM workspace is required.")
    return _positive_id(workspace.get("id"), label="Organization ID")
