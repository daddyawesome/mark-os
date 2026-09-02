from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from app.services.access_control import has_crm_owner_authority


Record = Mapping[str, Any] | sqlite3.Row


class ClientDeliveryPermissionError(PermissionError):
    """Raised when a CRM actor attempts a forbidden client-delivery action."""


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


def can_manage_clients(user: Record | None) -> bool:
    """Onboarding a client and structural engagement fields stay Owner-only."""
    return has_crm_owner_authority(user)


def is_delivery_owner(user: Record | None, engagement: Record | None) -> bool:
    actor_id = _positive_actor_id(user)
    if actor_id is None or engagement is None:
        return False
    return actor_id == _value(engagement, "delivery_owner_user_id")


def can_view_engagement(user: Record | None, engagement: Record | None) -> bool:
    if engagement is None:
        return False
    return has_crm_owner_authority(user) or is_delivery_owner(user, engagement)


def can_update_engagement_notes(user: Record | None, engagement: Record | None) -> bool:
    """The assigned delivery owner may keep notes current; Owner always can."""
    if engagement is None:
        return False
    if has_crm_owner_authority(user):
        return True
    return is_delivery_owner(user, engagement) and str(
        _value(engagement, "status", "")
    ) == "active"


def can_complete_engagement(user: Record | None, engagement: Record | None) -> bool:
    if engagement is None or str(_value(engagement, "status", "")) != "active":
        return False
    return has_crm_owner_authority(user) or is_delivery_owner(user, engagement)


def can_cancel_engagement(user: Record | None, engagement: Record | None) -> bool:
    if engagement is None or str(_value(engagement, "status", "")) != "active":
        return False
    return has_crm_owner_authority(user)


def can_manage_engagement_items(user: Record | None, engagement: Record | None) -> bool:
    """Create/update items: Owner, or the delivery owner while engagement is active."""
    if engagement is None:
        return False
    if has_crm_owner_authority(user):
        return True
    return is_delivery_owner(user, engagement) and str(
        _value(engagement, "status", "")
    ) == "active"
