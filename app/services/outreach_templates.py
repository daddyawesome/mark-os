from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from typing import Any

from app.db.organizations import organization_id_by_slug
from app.db.outreach_templates import TEMPLATE_CATEGORIES
from app.services.access_control import has_crm_owner_authority
from app.services.workspace_context import load_crm_actor_for_workspace


Record = Mapping[str, Any] | sqlite3.Row

MAX_TITLE_LENGTH = 200
MAX_BODY_LENGTH = 5_000

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class OutreachTemplatePermissionError(PermissionError):
    """Raised when an actor lacks authority over outreach templates."""


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _required_text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} is required.")
    if len(clean) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer.")
    return clean


def _organization_id(
    db: sqlite3.Connection,
    organization_id: int | None,
) -> int:
    if organization_id is None:
        return organization_id_by_slug(db, "mark-agency")
    return _positive_id(organization_id, "Organization ID")


def _actor_for_workspace(
    db: sqlite3.Connection,
    actor: Record,
    organization_id: int,
) -> Record:
    try:
        return load_crm_actor_for_workspace(db, actor, organization_id)
    except PermissionError as exc:
        raise OutreachTemplatePermissionError(
            "You are not allowed to access this CRM workspace."
        ) from exc


def _require_owner_authority(actor: Record) -> None:
    if not has_crm_owner_authority(actor):
        raise OutreachTemplatePermissionError(
            "Only Mark or workspace-owner authority can manage outreach "
            "templates."
        )


def _slugify(title: str) -> str:
    normalized = _SLUG_PATTERN.sub("-", title.strip().casefold()).strip("-")
    if not normalized:
        raise ValueError("Template title must contain a letter or number.")
    return normalized


def extract_template_variables(body: str) -> tuple[str, ...]:
    return tuple(sorted(set(_VARIABLE_PATTERN.findall(body))))


def render_template(body: str, variables: Mapping[str, str]) -> str:
    """Safely substitute ``{{variable}}`` placeholders with plain text.

    This is a fixed regex substitution over known ``{{name}}`` tokens only —
    never a template-engine ``render()`` call over Owner-authored text — so
    template bodies can never execute code or reach attributes/methods.
    Unresolved placeholders are left visible rather than silently blanked,
    so the preview always shows what still needs a value.
    """

    def _substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        value = variables.get(name)
        if value is None or str(value).strip() == "":
            return match.group(0)
        return str(value)

    return _VARIABLE_PATTERN.sub(_substitute, body)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["variables"] = list(extract_template_variables(str(data["body"])))
    return data


def list_templates(
    db: sqlite3.Connection,
    *,
    organization_id: int | None = None,
    approved_only: bool = False,
) -> list[dict[str, Any]]:
    safe_organization_id = _organization_id(db, organization_id)
    conditions = ["organization_id = ?", "active = 1"]
    parameters: list[Any] = [safe_organization_id]
    if approved_only:
        conditions.append("approved = 1")
    rows = db.execute(
        f"""
        SELECT *
        FROM outreach_templates
        WHERE {' AND '.join(conditions)}
        ORDER BY category, title COLLATE NOCASE
        """,
        parameters,
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_template(
    db: sqlite3.Connection,
    template_id: int,
    *,
    organization_id: int | None = None,
) -> dict[str, Any] | None:
    safe_organization_id = _organization_id(db, organization_id)
    row = db.execute(
        """
        SELECT *
        FROM outreach_templates
        WHERE id = ? AND organization_id = ? AND active = 1
        """,
        (_positive_id(template_id, "Template ID"), safe_organization_id),
    ).fetchone()
    return _row_to_dict(row) if row is not None else None


def create_template(
    db: sqlite3.Connection,
    *,
    actor: Record,
    organization_id: int | None,
    title: str,
    category: str,
    body: str,
) -> dict[str, Any]:
    safe_organization_id = _organization_id(db, organization_id)
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    _require_owner_authority(actor)

    clean_title = _required_text(title, "Template title", MAX_TITLE_LENGTH)
    clean_body = _required_text(body, "Template body", MAX_BODY_LENGTH)
    clean_category = str(category or "").strip()
    if clean_category not in TEMPLATE_CATEGORIES:
        raise ValueError("Unsupported template category.")

    slug = _slugify(clean_title)
    existing = db.execute(
        "SELECT 1 FROM outreach_templates WHERE organization_id = ? AND slug = ?",
        (safe_organization_id, slug),
    ).fetchone()
    if existing is not None:
        raise ValueError("A template with this title already exists.")

    actor_id = int(actor["id"]) if actor.get("id") else None
    cursor = db.execute(
        """
        INSERT INTO outreach_templates (
            organization_id, slug, title, category, body,
            created_by_user_id, updated_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            slug,
            clean_title,
            clean_category,
            clean_body,
            actor_id,
            actor_id,
        ),
    )
    return get_template(
        db,
        cursor.lastrowid,
        organization_id=safe_organization_id,
    )


def update_template(
    db: sqlite3.Connection,
    template_id: int,
    *,
    actor: Record,
    organization_id: int | None,
    title: str,
    category: str,
    body: str,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    safe_organization_id = _organization_id(db, organization_id)
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    _require_owner_authority(actor)

    current = get_template(
        db,
        template_id,
        organization_id=safe_organization_id,
    )
    if current is None:
        raise ValueError("Template not found.")
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This template changed in another session.")

    clean_title = _required_text(title, "Template title", MAX_TITLE_LENGTH)
    clean_body = _required_text(body, "Template body", MAX_BODY_LENGTH)
    clean_category = str(category or "").strip()
    if clean_category not in TEMPLATE_CATEGORIES:
        raise ValueError("Unsupported template category.")

    actor_id = int(actor["id"]) if actor.get("id") else None
    cursor = db.execute(
        """
        UPDATE outreach_templates
        SET title = ?,
            category = ?,
            body = ?,
            updated_by_user_id = ?,
            row_version = row_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND active = 1
          AND (? IS NULL OR row_version = ?)
        """,
        (
            clean_title,
            clean_category,
            clean_body,
            actor_id,
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This template changed in another session.")
    return get_template(
        db,
        template_id,
        organization_id=safe_organization_id,
    )


def set_template_approval(
    db: sqlite3.Connection,
    template_id: int,
    *,
    actor: Record,
    organization_id: int | None,
    approved: bool,
    expected_row_version: int | None = None,
) -> dict[str, Any]:
    safe_organization_id = _organization_id(db, organization_id)
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    _require_owner_authority(actor)

    current = get_template(
        db,
        template_id,
        organization_id=safe_organization_id,
    )
    if current is None:
        raise ValueError("Template not found.")
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This template changed in another session.")

    actor_id = int(actor["id"]) if actor.get("id") else None
    cursor = db.execute(
        """
        UPDATE outreach_templates
        SET approved = ?,
            approved_by_user_id = CASE WHEN ? THEN ? ELSE NULL END,
            approved_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
            row_version = row_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND active = 1
          AND (? IS NULL OR row_version = ?)
        """,
        (
            1 if approved else 0,
            1 if approved else 0,
            actor_id,
            1 if approved else 0,
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This template changed in another session.")
    return get_template(
        db,
        template_id,
        organization_id=safe_organization_id,
    )


def archive_template(
    db: sqlite3.Connection,
    template_id: int,
    *,
    actor: Record,
    organization_id: int | None,
    expected_row_version: int | None = None,
) -> None:
    safe_organization_id = _organization_id(db, organization_id)
    actor = _actor_for_workspace(db, actor, safe_organization_id)
    _require_owner_authority(actor)

    current = get_template(
        db,
        template_id,
        organization_id=safe_organization_id,
    )
    if current is None:
        raise ValueError("Template not found.")
    if (
        expected_row_version is not None
        and int(current["row_version"]) != int(expected_row_version)
    ):
        raise ValueError("This template changed in another session.")

    cursor = db.execute(
        """
        UPDATE outreach_templates
        SET active = 0,
            row_version = row_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND organization_id = ? AND active = 1
          AND (? IS NULL OR row_version = ?)
        """,
        (
            int(current["id"]),
            safe_organization_id,
            expected_row_version,
            expected_row_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("This template changed in another session.")
