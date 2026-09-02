from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from app.services.access_control import has_crm_owner_authority, is_relationship_manager


Record = Mapping[str, Any] | sqlite3.Row


class ProposalPermissionError(PermissionError):
    """Raised when a CRM actor attempts a forbidden proposal action."""


def _value(record: Record | None, key: str, default: Any = None) -> Any:
    if record is None:
        return default
    try:
        return record[key]
    except (KeyError, IndexError, TypeError):
        return default


def _positive_actor_id(user: Record | None) -> int | None:
    value = _value(user, "id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def can_view_proposals_for_lead(user: Record | None, lead: Record | None) -> bool:
    """Mirrors lead visibility: Owner/workspace-owner, or the lead's own RM."""
    if lead is None:
        return False
    if has_crm_owner_authority(user):
        return True
    if is_relationship_manager(user):
        actor_id = _positive_actor_id(user)
        if actor_id is None:
            return False
        return actor_id in {
            _value(lead, "created_by_user_id"),
            _value(lead, "business_development_owner_user_id"),
        }
    return False


def can_manage_proposals(user: Record | None) -> bool:
    """Mark retains pricing and proposal authority — no shared editing."""
    return has_crm_owner_authority(user)
