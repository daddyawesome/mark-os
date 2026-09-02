from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from app.db.lead_qualification import QUALIFICATION_STATUSES
from app.services.access_control import has_crm_owner_authority, is_relationship_manager


Record = Mapping[str, Any] | sqlite3.Row

DECIDED_QUALIFICATION_STATUSES = frozenset({"qualified", "disqualified"})


class LeadQualificationPermissionError(PermissionError):
    """Raised when a CRM actor attempts a forbidden qualification action."""


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


def _lead_is_active(lead: Record | None) -> bool:
    return lead is not None and _value(lead, "deleted_at") is None


def can_edit_qualification(user: Record | None, lead: Record | None) -> bool:
    if not _lead_is_active(lead):
        return False
    if has_crm_owner_authority(user):
        return True
    if is_relationship_manager(user):
        actor_id = _positive_actor_id(user)
        if actor_id is None:
            return False
        owns_relationship = (
            actor_id == _value(lead, "business_development_owner_user_id")
        )
        status = str(_value(lead, "qualification_status", "") or "")
        return owns_relationship and status not in DECIDED_QUALIFICATION_STATUSES
    return False


def can_decide_qualification(user: Record | None, lead: Record | None) -> bool:
    if not _lead_is_active(lead):
        return False
    status = str(_value(lead, "qualification_status", "") or "")
    return (
        has_crm_owner_authority(user)
        and status not in DECIDED_QUALIFICATION_STATUSES
    )


def require_qualification_decision(decision: str) -> str:
    normalized = str(decision or "").strip().casefold()
    if normalized not in DECIDED_QUALIFICATION_STATUSES:
        raise ValueError(
            "Qualification decision must be 'qualified' or 'disqualified'."
        )
    return normalized


assert set(DECIDED_QUALIFICATION_STATUSES).issubset(set(QUALIFICATION_STATUSES))
