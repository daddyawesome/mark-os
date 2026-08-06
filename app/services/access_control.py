from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


OWNER_ROLE = "owner"
MEMBER_ROLE = "member"
LEAD_SOURCER_ROLE = "lead_sourcer"
RELATIONSHIP_MANAGER_ROLE = "relationship_manager"

_LEAD_DETAIL_PATTERN = re.compile(r"^/crm/leads/[1-9][0-9]*$")
_LEAD_RESEARCH_EDIT_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/research/edit$"
)
_LEAD_RESEARCH_SUBMIT_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/research/submit$"
)
_LEAD_ACTIVITY_CREATE_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/activities$"
)
_LEAD_ACTIVITY_ACTION_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/activities/"
    r"[1-9][0-9]*/(?:correct|delete)$"
)
_RELATIONSHIP_NEXT_ACTION_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/next-action$"
)

_QUEST_DETAIL_PATTERN = re.compile(r"^/quests/[1-9][0-9]*$")
_HISTORY_EDIT_PATTERN = re.compile(
    r"^/history/[1-9][0-9]*/edit$"
)
_HISTORY_DELETE_PATTERN = re.compile(
    r"^/history/[1-9][0-9]*/delete$"
)
_PROJECT_LINK_PATTERN = re.compile(
    r"^/projects/[1-9][0-9]*/link-goal$"
)
_QUEST_ACTION_PATTERN = re.compile(
    r"^/quests/[1-9][0-9]*/"
    r"(?:start|block|unblock|abandon|update|complete)$"
)

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


_RELATIONSHIP_MANAGER_GET_PATHS = frozenset(
    {
        "/relationship-manager",
        "/crm",
        "/crm/leads/new",
        "/crm/leads/import/template",
    }
)

_RELATIONSHIP_MANAGER_POST_PATHS = frozenset(
    {
        "/crm/leads",
        "/crm/leads/import",
        "/logout",
    }
)

_MEMBER_GET_PATHS = frozenset(
    {
        "/",
        "/quests",
        "/goals",
        "/life-os",
        "/history",
        "/family/setup",
    }
)

_MEMBER_POST_PATHS = frozenset(
    {
        "/check-in",
        "/goals",
        "/quests",
        "/logout",
    }
)


def role_of(user: Mapping[str, Any] | None) -> str:
    if user is None:
        return ""
    return str(user.get("role") or "").strip().casefold()


def is_owner(user: Mapping[str, Any] | None) -> bool:
    return role_of(user) == OWNER_ROLE


def is_member(user: Mapping[str, Any] | None) -> bool:
    return role_of(user) == MEMBER_ROLE


def is_lead_sourcer(user: Mapping[str, Any] | None) -> bool:
    return role_of(user) == LEAD_SOURCER_ROLE


def is_relationship_manager(
    user: Mapping[str, Any] | None,
) -> bool:
    return role_of(user) == RELATIONSHIP_MANAGER_ROLE


def is_personal_user(user: Mapping[str, Any] | None) -> bool:
    return role_of(user) in {OWNER_ROLE, MEMBER_ROLE}


def landing_path_for_user(user: Mapping[str, Any]) -> str:
    if is_personal_user(user):
        return "/"
    if is_relationship_manager(user):
        return "/relationship-manager"
    return "/crm"


def _member_can_get(path: str) -> bool:
    return (
        path in _MEMBER_GET_PATHS
        or _QUEST_DETAIL_PATTERN.fullmatch(path) is not None
        or _HISTORY_EDIT_PATTERN.fullmatch(path) is not None
    )


def _member_can_post(path: str) -> bool:
    return (
        path in _MEMBER_POST_PATHS
        or _HISTORY_EDIT_PATTERN.fullmatch(path) is not None
        or _HISTORY_DELETE_PATTERN.fullmatch(path) is not None
        or _PROJECT_LINK_PATTERN.fullmatch(path) is not None
        or _QUEST_ACTION_PATTERN.fullmatch(path) is not None
    )


def can_access_request(
    user: Mapping[str, Any] | None,
    method: str,
    path: str,
) -> bool:
    """Authorize the final M10 role surfaces.

    Owners retain the complete application. Members receive only their private
    personal OS. Lead sourcers keep the narrow CRM-only capability from M3-M7.
    """
    if is_owner(user):
        return True

    normalized_method = (method or "").upper()
    normalized_path = path or "/"

    if is_member(user):
        if normalized_method in {"GET", "HEAD"}:
            return _member_can_get(normalized_path)
        if normalized_method == "POST":
            return _member_can_post(normalized_path)
        return False

    if is_relationship_manager(user):
        if normalized_method in {"GET", "HEAD"}:
            return (
                normalized_path in _RELATIONSHIP_MANAGER_GET_PATHS
                or _LEAD_DETAIL_PATTERN.fullmatch(normalized_path) is not None
            )
        if normalized_method == "POST":
            return (
                normalized_path in _RELATIONSHIP_MANAGER_POST_PATHS
                or _RELATIONSHIP_NEXT_ACTION_PATTERN.fullmatch(
                    normalized_path
                )
                is not None
            )
        return False

    if not is_lead_sourcer(user):
        return False

    if normalized_method in {"GET", "HEAD"}:
        return (
            normalized_path in _LEAD_SOURCER_GET_PATHS
            or _LEAD_DETAIL_PATTERN.fullmatch(normalized_path) is not None
            or _LEAD_RESEARCH_EDIT_PATTERN.fullmatch(normalized_path) is not None
        )

    if normalized_method == "POST":
        return (
            normalized_path in _LEAD_SOURCER_POST_PATHS
            or _LEAD_RESEARCH_EDIT_PATTERN.fullmatch(normalized_path) is not None
            or _LEAD_RESEARCH_SUBMIT_PATTERN.fullmatch(normalized_path) is not None
            or _LEAD_ACTIVITY_CREATE_PATTERN.fullmatch(
                normalized_path
            )
            is not None
            or _LEAD_ACTIVITY_ACTION_PATTERN.fullmatch(
                normalized_path
            )
            is not None
        )

    return False


def permitted_destination(
    user: Mapping[str, Any],
    destination: str,
) -> str:
    if can_access_request(user, "GET", destination):
        return destination
    return landing_path_for_user(user)
