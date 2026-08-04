from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


OWNER_ROLE = "owner"
LEAD_SOURCER_ROLE = "lead_sourcer"

_LEAD_DETAIL_PATTERN = re.compile(r"^/crm/leads/[1-9][0-9]*$")

_LEAD_SOURCER_GET_PATHS = frozenset(
    {
        "/crm",
        "/crm/leads/new",
        "/crm/leads/import/template",
    }
)

_LEAD_SOURCER_POST_PATHS = frozenset(
    {
        "/crm/leads",
        "/crm/leads/import",
        "/logout",
    }
)


def role_of(user: Mapping[str, Any] | None) -> str:
    if user is None:
        return ""
    return str(user.get("role") or "").strip().casefold()


def is_owner(user: Mapping[str, Any] | None) -> bool:
    return role_of(user) == OWNER_ROLE


def is_lead_sourcer(user: Mapping[str, Any] | None) -> bool:
    return role_of(user) == LEAD_SOURCER_ROLE


def landing_path_for_user(user: Mapping[str, Any]) -> str:
    return "/" if is_owner(user) else "/crm"


def can_access_request(
    user: Mapping[str, Any] | None,
    method: str,
    path: str,
) -> bool:
    """Return whether an authenticated user may access one request.

    Owners retain full MARK-OS access. Lead sourcers receive the smallest
    useful CRM surface: dashboard, add/import, template download, and read-only
    lead detail pages.
    """
    if is_owner(user):
        return True

    if not is_lead_sourcer(user):
        return False

    normalized_method = (method or "").upper()
    normalized_path = path or "/"

    if normalized_method in {"GET", "HEAD"}:
        return (
            normalized_path in _LEAD_SOURCER_GET_PATHS
            or _LEAD_DETAIL_PATTERN.fullmatch(normalized_path) is not None
        )

    if normalized_method == "POST":
        return normalized_path in _LEAD_SOURCER_POST_PATHS

    return False


def permitted_destination(
    user: Mapping[str, Any],
    destination: str,
) -> str:
    """Keep login redirects inside the user's authorized area."""
    if can_access_request(user, "GET", destination):
        return destination
    return landing_path_for_user(user)
