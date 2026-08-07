from __future__ import annotations

import sqlite3
from collections.abc import Mapping, MutableMapping
from typing import Any

from fastapi import Request


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

    role = str(user.get("role") or "").strip().casefold()
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
        """,
        (user_id, safe_organization_id),
    ).fetchone()
    if workspace is None:
        raise PermissionError("Workspace is not authorized for this user.")

    session[SESSION_CURRENT_ORGANIZATION_ID_KEY] = safe_organization_id
    return dict(workspace)


def request_current_workspace(request: Request) -> dict[str, Any] | None:
    workspace = getattr(request.state, "current_workspace", None)
    return workspace if isinstance(workspace, dict) else None


def require_request_organization_id(request: Request) -> int:
    workspace = request_current_workspace(request)
    if workspace is None:
        raise RuntimeError("Current workspace context is unavailable.")
    return _positive_id(workspace.get("id"), label="Organization ID")
