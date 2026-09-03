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
_LEAD_QUALIFICATION_EDIT_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/qualification/edit$"
)
_LEAD_QUALIFICATION_DECIDE_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/qualification/decide$"
)
_LEAD_PROPOSALS_LIST_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/proposals$"
)
_LEAD_PROPOSAL_DETAIL_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/proposals/[1-9][0-9]*$"
)
_LEAD_PROPOSAL_ACTION_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/proposals/[1-9][0-9]*/"
    r"(?:edit|submit-review|approve|send|decision)$"
)
_LEAD_ONBOARD_PATTERN = re.compile(r"^/crm/leads/[1-9][0-9]*/onboard$")
_CLIENT_DETAIL_PATTERN = re.compile(r"^/crm/clients/[1-9][0-9]*$")
_CLIENT_ENGAGEMENTS_CREATE_PATTERN = re.compile(
    r"^/crm/clients/[1-9][0-9]*/engagements$"
)
_ENGAGEMENT_DETAIL_PATTERN = re.compile(r"^/crm/engagements/[1-9][0-9]*$")
_ENGAGEMENT_DELIVERY_ACTION_PATTERN = re.compile(
    r"^/crm/engagements/[1-9][0-9]*/(?:notes|complete|items)$"
)
_ENGAGEMENT_OWNER_ACTION_PATTERN = re.compile(
    r"^/crm/engagements/[1-9][0-9]*/(?:edit|cancel)$"
)
_ENGAGEMENT_ITEM_STATUS_PATTERN = re.compile(
    r"^/crm/engagements/[1-9][0-9]*/items/[1-9][0-9]*/status$"
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
_WORKSPACE_OWNER_EDIT_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/edit$"
)
_WORKSPACE_OWNER_PIPELINE_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/pipeline$"
)
_WORKSPACE_OWNER_RELATIONSHIP_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/relationship-owner$"
)
_WORKSPACE_OWNER_DELETE_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/delete$"
)
_WORKSPACE_OWNER_RESEARCH_REVIEW_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/research/review$"
)
_WORKSPACE_OWNER_OUTREACH_PATTERN = re.compile(
    r"^/crm/leads/[1-9][0-9]*/outreach/approve$"
)
_TEMPLATE_USE_PATTERN = re.compile(r"^/crm/templates/[1-9][0-9]*/use$")
_TEMPLATE_EDIT_PATTERN = re.compile(r"^/crm/templates/[1-9][0-9]*/edit$")
_TEMPLATE_MANAGE_ACTION_PATTERN = re.compile(
    r"^/crm/templates/[1-9][0-9]*/(?:approve|unapprove|archive)$"
)
_WEBHOOK_TOKEN_REVOKE_PATTERN = re.compile(
    r"^/crm/webhooks/[1-9][0-9]*/revoke$"
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
        "/crm/follow-ups",
        "/crm/leads/new",
        "/crm/leads/import/template",
        "/crm/leads/export",
        "/crm/effort",
    }
)

_LEAD_SOURCER_POST_PATHS = frozenset(
    {
        "/crm/leads",
        "/crm/leads/import",
        "/crm/leads/research/bulk-submit",
        "/logout",
    }
)


_RELATIONSHIP_MANAGER_GET_PATHS = frozenset(
    {
        "/relationship-manager",
        "/crm",
        "/crm/follow-ups",
        "/crm/leads/new",
        "/crm/leads/import/template",
        "/crm/leads/export",
        "/crm/templates",
        "/crm/effort",
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


def workspace_membership_role_of(
    user: Mapping[str, Any] | None,
) -> str:
    if user is None:
        return ""
    direct = str(user.get("workspace_membership_role") or "").strip().casefold()
    if direct:
        return direct
    workspace = user.get("current_workspace")
    if isinstance(workspace, Mapping):
        return str(workspace.get("membership_role") or "").strip().casefold()
    return ""


def is_workspace_owner_manager(
    user: Mapping[str, Any] | None,
) -> bool:
    """Pendang-style owner authority without granting global Owner."""
    return (
        is_relationship_manager(user)
        and workspace_membership_role_of(user) == "workspace_owner"
    )


def has_crm_owner_authority(
    user: Mapping[str, Any] | None,
) -> bool:
    return is_owner(user) or is_workspace_owner_manager(user)


def is_personal_user(user: Mapping[str, Any] | None) -> bool:
    return role_of(user) in {OWNER_ROLE, MEMBER_ROLE}


def _active_workspace_slug(user: Mapping[str, Any] | None) -> str:
    if user is None:
        return ""
    workspace = user.get("current_workspace")
    if not isinstance(workspace, Mapping):
        return ""
    return str(workspace.get("slug") or "").strip().casefold()


def landing_path_for_user(user: Mapping[str, Any]) -> str:
    role = role_of(user)
    if (
        _active_workspace_slug(user) == "pendang"
        and role in {OWNER_ROLE, LEAD_SOURCER_ROLE, RELATIONSHIP_MANAGER_ROLE}
    ):
        return "/pendang"
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
    """Authorize personal, CRM, and Pendang company-workspace surfaces."""
    normalized_method = (method or "").upper()
    normalized_path = path or "/"

    is_pendang_path = (
        normalized_path == "/pendang"
        or normalized_path.startswith("/pendang/")
    )
    if is_pendang_path:
        if _active_workspace_slug(user) != "pendang":
            return False
        if normalized_method in {"GET", "HEAD"}:
            return normalized_path == "/pendang" and role_of(user) in {
                OWNER_ROLE,
                LEAD_SOURCER_ROLE,
                RELATIONSHIP_MANAGER_ROLE,
            }
        if normalized_method == "POST":
            return (
                role_of(user) in {OWNER_ROLE, RELATIONSHIP_MANAGER_ROLE}
                and (
                    is_owner(user)
                    or workspace_membership_role_of(user)
                    in {"workspace_admin", "workspace_owner"}
                )
            )
        return False

    if is_owner(user):
        return True

    if normalized_path == "/notifications" and normalized_method in {
        "GET", "HEAD"
    }:
        return True
    if normalized_path == "/insights" and normalized_method in {"GET", "HEAD"}:
        return True
    if normalized_path in {"/account/export", "/account/export/download"} and normalized_method in {"GET", "HEAD"}:
        return True

    if normalized_path == "/account/sessions" and normalized_method in {
        "GET", "HEAD"
    }:
        return True
    if (
        normalized_path == "/account/sessions/revoke-others"
        and normalized_method == "POST"
    ):
        return True

    if (
        normalized_path == "/account/password"
        and normalized_method in {"GET", "HEAD", "POST"}
    ):
        return True

    if is_member(user):
        if normalized_method in {"GET", "HEAD"}:
            return _member_can_get(normalized_path)
        if normalized_method == "POST":
            return _member_can_post(normalized_path)
        return False

    if is_relationship_manager(user):
        workspace_owner = is_workspace_owner_manager(user)
        if normalized_method in {"GET", "HEAD"}:
            return (
                normalized_path in _RELATIONSHIP_MANAGER_GET_PATHS
                or _LEAD_DETAIL_PATTERN.fullmatch(normalized_path) is not None
                or _TEMPLATE_USE_PATTERN.fullmatch(normalized_path) is not None
                or _LEAD_QUALIFICATION_EDIT_PATTERN.fullmatch(
                    normalized_path
                )
                is not None
                or _LEAD_PROPOSALS_LIST_PATTERN.fullmatch(
                    normalized_path
                )
                is not None
                or _LEAD_PROPOSAL_DETAIL_PATTERN.fullmatch(
                    normalized_path
                )
                is not None
                or _CLIENT_DETAIL_PATTERN.fullmatch(normalized_path) is not None
                or _ENGAGEMENT_DETAIL_PATTERN.fullmatch(normalized_path) is not None
                or (
                    workspace_owner
                    and (
                        normalized_path == "/crm/clients"
                        or normalized_path == "/crm/research-review"
                        or normalized_path == "/crm/templates/new"
                        or normalized_path == "/crm/webhooks"
                        or _WORKSPACE_OWNER_EDIT_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _WORKSPACE_OWNER_DELETE_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _TEMPLATE_EDIT_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                    )
                )
            )
        if normalized_method == "POST":
            return (
                normalized_path in _RELATIONSHIP_MANAGER_POST_PATHS
                or _RELATIONSHIP_NEXT_ACTION_PATTERN.fullmatch(
                    normalized_path
                )
                is not None
                or _TEMPLATE_USE_PATTERN.fullmatch(normalized_path) is not None
                or _LEAD_QUALIFICATION_EDIT_PATTERN.fullmatch(
                    normalized_path
                )
                is not None
                or _ENGAGEMENT_DELIVERY_ACTION_PATTERN.fullmatch(
                    normalized_path
                )
                is not None
                or _ENGAGEMENT_ITEM_STATUS_PATTERN.fullmatch(
                    normalized_path
                )
                is not None
                or (
                    # Phase 6.13: reachable by any Relationship Manager, not
                    # just workspace-owner authority — the delegated-contact
                    # service-layer gate (can_perform_delegated_contact) is
                    # the real, authoritative restriction, mirroring how
                    # every other narrow-condition route in this branch
                    # already works. Without the flag and lead ownership,
                    # change_pipeline_stage and create_activity still reject
                    # everything except an owner-authority actor.
                    _WORKSPACE_OWNER_PIPELINE_PATTERN.fullmatch(
                        normalized_path
                    )
                    is not None
                    or _LEAD_ACTIVITY_CREATE_PATTERN.fullmatch(
                        normalized_path
                    )
                    is not None
                )
                or (
                    workspace_owner
                    and (
                        normalized_path == "/crm/templates"
                        or _ENGAGEMENT_OWNER_ACTION_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or normalized_path == "/crm/webhooks"
                        or _LEAD_ONBOARD_PATTERN.fullmatch(normalized_path)
                        is not None
                        or _CLIENT_ENGAGEMENTS_CREATE_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _LEAD_PROPOSALS_LIST_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _LEAD_PROPOSAL_ACTION_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _TEMPLATE_EDIT_PATTERN.fullmatch(normalized_path)
                        is not None
                        or _TEMPLATE_MANAGE_ACTION_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _WEBHOOK_TOKEN_REVOKE_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _LEAD_QUALIFICATION_DECIDE_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _WORKSPACE_OWNER_EDIT_PATTERN.fullmatch(normalized_path)
                        is not None
                        or _WORKSPACE_OWNER_RELATIONSHIP_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _WORKSPACE_OWNER_DELETE_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _WORKSPACE_OWNER_RESEARCH_REVIEW_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _WORKSPACE_OWNER_OUTREACH_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                        or _LEAD_ACTIVITY_ACTION_PATTERN.fullmatch(
                            normalized_path
                        )
                        is not None
                    )
                )
            )
        return False

    if not is_lead_sourcer(user):
        return False

    if normalized_method in {"GET", "HEAD"}:
        return (
            normalized_path in _LEAD_SOURCER_GET_PATHS
            or _LEAD_DETAIL_PATTERN.fullmatch(normalized_path) is not None
            or _LEAD_RESEARCH_EDIT_PATTERN.fullmatch(normalized_path) is not None
            or _ENGAGEMENT_DETAIL_PATTERN.fullmatch(normalized_path) is not None
        )

    if normalized_method == "POST":
        return (
            normalized_path in _LEAD_SOURCER_POST_PATHS
            or _LEAD_RESEARCH_EDIT_PATTERN.fullmatch(normalized_path) is not None
            or _LEAD_RESEARCH_SUBMIT_PATTERN.fullmatch(normalized_path) is not None
            or _LEAD_ACTIVITY_CREATE_PATTERN.fullmatch(normalized_path) is not None
            or _LEAD_ACTIVITY_ACTION_PATTERN.fullmatch(normalized_path) is not None
            or _ENGAGEMENT_DELIVERY_ACTION_PATTERN.fullmatch(
                normalized_path
            )
            is not None
            or _ENGAGEMENT_ITEM_STATUS_PATTERN.fullmatch(
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
