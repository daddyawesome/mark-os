from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from app.db.organizations import organization_id_by_slug
from app.db.pendang_company import ITEM_TYPES
from app.services.workspace_context import load_crm_actor_for_workspace


ITEM_STATUSES = ("draft", "active")

ITEM_TYPE_LABELS = {
    "service": "Services & Pricing",
    "project": "Historical Projects",
    "case_study": "Case Studies",
    "relationship": "Warm Relationships",
    "content_draft": "Content Studio",
    "meeting_preparation": "Meeting Preparation",
    "document": "Shared Company Documents",
}

SECTIONS = (
    {
        "key": "service",
        "title": "Services & Pricing",
        "empty": "No verified service entries have been recorded yet.",
        "details_label": "Pricing / service details",
        "note": "Record real offers and pricing guidance; do not invent client commitments.",
    },
    {
        "key": "project",
        "title": "Historical Projects",
        "empty": "No verified historical projects have been recorded yet.",
        "details_label": "Project details",
        "note": "Add only work the team can accurately describe and support with evidence.",
    },
    {
        "key": "case_study",
        "title": "Case Studies",
        "empty": "No verified case studies have been recorded yet.",
        "details_label": "Evidence / outcome details",
        "note": "Keep claims factual and anonymize confidential client information.",
    },
    {
        "key": "relationship",
        "title": "Warm Relationships",
        "empty": "No warm relationships have been recorded yet.",
        "details_label": "Relationship context",
        "note": "Store business context only; avoid unnecessary private personal information.",
    },
    {
        "key": "content_draft",
        "title": "Content Studio",
        "empty": "No content drafts have been recorded yet.",
        "details_label": "Channel / publishing notes",
        "note": "Manual draft storage only. This does not generate AI content or publish externally.",
    },
    {
        "key": "meeting_preparation",
        "title": "Meeting Preparation",
        "empty": "No meeting-preparation records have been created yet.",
        "details_label": "Agenda / preparation details",
        "note": "Use this for upcoming business meetings and verified preparation notes.",
    },
    {
        "key": "document",
        "title": "Shared Company Documents",
        "empty": "No shared company-document links have been recorded yet.",
        "details_label": "Document context",
        "note": "Store a trusted reference link and context; this phase does not upload file bytes.",
    },
)


class PendangCompanyPermissionError(PermissionError):
    pass


class PendangCompanyNotFoundError(LookupError):
    pass


class PendangCompanyConflictError(RuntimeError):
    pass


def _clean(value: Any, *, label: str, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{label} is required.")
    if len(text) > maximum:
        raise ValueError(f"{label} must be {maximum} characters or fewer.")
    return text


def _positive_version(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Row version is invalid.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Row version is invalid.") from exc
    if parsed < 1:
        raise ValueError("Row version is invalid.")
    return parsed


def _clean_url(value: Any) -> str:
    text = _clean(value, label="Reference URL", maximum=2048)
    if not text:
        return ""
    parsed = urlsplit(text)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Reference URL must be a complete http:// or https:// URL.")
    return text


def _clean_date(value: Any) -> str | None:
    text = _clean(value, label="Scheduled date", maximum=10)
    if not text:
        return None
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("Scheduled date must use YYYY-MM-DD.") from exc
    return text


def _active_workspace_slug(actor: Mapping[str, Any]) -> str:
    workspace = actor.get("current_workspace")
    if not isinstance(workspace, Mapping):
        return ""
    return str(workspace.get("slug") or "").strip().casefold()


def _authorized_actor(
    db: sqlite3.Connection,
    actor: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    if _active_workspace_slug(actor) != "pendang":
        raise PendangCompanyPermissionError(
            "The Pendang company workspace requires an active Pendang membership."
        )

    organization_id = organization_id_by_slug(db, "pendang")
    try:
        database_actor = load_crm_actor_for_workspace(
            db,
            actor,
            organization_id,
        )
    except (PermissionError, ValueError) as exc:
        raise PendangCompanyPermissionError(
            "The Pendang company workspace is not authorized for this user."
        ) from exc
    return database_actor, organization_id


def _can_manage_actor(actor: Mapping[str, Any]) -> bool:
    global_role = str(actor.get("role") or "").strip().casefold()
    membership_role = str(
        actor.get("workspace_membership_role")
        or (
            actor.get("current_workspace", {}).get("membership_role")
            if isinstance(actor.get("current_workspace"), Mapping)
            else ""
        )
        or ""
    ).strip().casefold()
    if global_role == "owner":
        return membership_role in {"workspace_admin", "workspace_owner"}
    return (
        global_role == "relationship_manager"
        and membership_role in {"workspace_admin", "workspace_owner"}
    )


def require_manage_authority(
    db: sqlite3.Connection,
    actor: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    database_actor, organization_id = _authorized_actor(db, actor)
    if not _can_manage_actor(database_actor):
        raise PendangCompanyPermissionError(
            "This Pendang membership is read-only for company knowledge."
        )
    return database_actor, organization_id


def load_company_home(
    db: sqlite3.Connection,
    actor: Mapping[str, Any],
) -> dict[str, Any]:
    database_actor, organization_id = _authorized_actor(db, actor)
    organization = db.execute(
        "SELECT id, slug, name FROM organizations WHERE id = ?",
        (organization_id,),
    ).fetchone()
    profile = db.execute(
        """
        SELECT organization_id, founder_plan, about_company, company_cv,
               row_version, created_by_user_id, updated_by_user_id,
               created_at, updated_at
        FROM organization_company_profiles
        WHERE organization_id = ?
        """,
        (organization_id,),
    ).fetchone()
    if organization is None or profile is None:
        raise RuntimeError("Pendang company workspace has not been initialized.")

    rows = db.execute(
        """
        SELECT id, organization_id, item_type, title, subtitle, body, details,
               reference_url, scheduled_for, status, row_version,
               created_by_user_id, updated_by_user_id,
               created_at, updated_at
        FROM organization_knowledge_items
        WHERE organization_id = ?
          AND deleted_at IS NULL
        ORDER BY
            CASE status WHEN 'active' THEN 0 ELSE 1 END,
            item_type,
            title COLLATE NOCASE,
            id
        """,
        (organization_id,),
    ).fetchall()

    items_by_type = {item_type: [] for item_type in ITEM_TYPES}
    for row in rows:
        items_by_type[str(row["item_type"])].append(dict(row))

    return {
        "organization": dict(organization),
        "profile": dict(profile),
        "items_by_type": items_by_type,
        "can_manage": _can_manage_actor(database_actor),
        "actor": database_actor,
    }


def update_company_profile(
    db: sqlite3.Connection,
    actor: Mapping[str, Any],
    *,
    founder_plan: Any,
    about_company: Any,
    company_cv: Any,
    expected_row_version: Any,
) -> dict[str, Any]:
    database_actor, organization_id = require_manage_authority(db, actor)
    expected = _positive_version(expected_row_version)
    founder = _clean(
        founder_plan,
        label="Founder Plan",
        maximum=20000,
        required=True,
    )
    about = _clean(about_company, label="About / Company CV summary", maximum=20000)
    cv = _clean(company_cv, label="Company CV", maximum=20000)

    cursor = db.execute(
        """
        UPDATE organization_company_profiles
        SET founder_plan = ?,
            about_company = ?,
            company_cv = ?,
            created_by_user_id = COALESCE(created_by_user_id, ?),
            updated_by_user_id = ?,
            row_version = row_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE organization_id = ?
          AND row_version = ?
        """,
        (
            founder,
            about,
            cv,
            int(database_actor["id"]),
            int(database_actor["id"]),
            organization_id,
            expected,
        ),
    )
    if cursor.rowcount != 1:
        raise PendangCompanyConflictError(
            "The company profile changed in another session. Reload and try again."
        )

    row = db.execute(
        """
        SELECT organization_id, founder_plan, about_company, company_cv,
               row_version, created_by_user_id, updated_by_user_id,
               created_at, updated_at
        FROM organization_company_profiles
        WHERE organization_id = ?
        """,
        (organization_id,),
    ).fetchone()
    return dict(row)


def create_knowledge_item(
    db: sqlite3.Connection,
    actor: Mapping[str, Any],
    *,
    item_type: Any,
    title: Any,
    subtitle: Any = "",
    body: Any = "",
    details: Any = "",
    reference_url: Any = "",
    scheduled_for: Any = "",
    status: Any = "draft",
) -> dict[str, Any]:
    database_actor, organization_id = require_manage_authority(db, actor)
    normalized_type = _clean(item_type, label="Item type", maximum=40, required=True)
    if normalized_type not in ITEM_TYPES:
        raise ValueError("Company knowledge item type is invalid.")
    normalized_status = _clean(status, label="Status", maximum=20, required=True)
    if normalized_status not in ITEM_STATUSES:
        raise ValueError("Status must be draft or active.")

    values = {
        "title": _clean(title, label="Title", maximum=160, required=True),
        "subtitle": _clean(subtitle, label="Subtitle", maximum=240),
        "body": _clean(body, label="Body", maximum=12000),
        "details": _clean(details, label="Details", maximum=8000),
        "reference_url": _clean_url(reference_url),
        "scheduled_for": _clean_date(scheduled_for),
    }

    try:
        cursor = db.execute(
            """
            INSERT INTO organization_knowledge_items (
                organization_id,
                item_type,
                title,
                subtitle,
                body,
                details,
                reference_url,
                scheduled_for,
                status,
                created_by_user_id,
                updated_by_user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                normalized_type,
                values["title"],
                values["subtitle"],
                values["body"],
                values["details"],
                values["reference_url"],
                values["scheduled_for"],
                normalized_status,
                int(database_actor["id"]),
                int(database_actor["id"]),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            "An active entry with this title already exists in this Pendang section."
        ) from exc

    row = db.execute(
        """
        SELECT id, organization_id, item_type, title, subtitle, body, details,
               reference_url, scheduled_for, status, row_version,
               created_by_user_id, updated_by_user_id, created_at, updated_at
        FROM organization_knowledge_items
        WHERE id = ? AND organization_id = ?
        """,
        (int(cursor.lastrowid), organization_id),
    ).fetchone()
    return dict(row)


def update_knowledge_item(
    db: sqlite3.Connection,
    actor: Mapping[str, Any],
    item_id: int,
    *,
    title: Any,
    subtitle: Any = "",
    body: Any = "",
    details: Any = "",
    reference_url: Any = "",
    scheduled_for: Any = "",
    status: Any = "draft",
    expected_row_version: Any,
) -> dict[str, Any]:
    database_actor, organization_id = require_manage_authority(db, actor)
    expected = _positive_version(expected_row_version)
    current = db.execute(
        """
        SELECT id
        FROM organization_knowledge_items
        WHERE id = ?
          AND organization_id = ?
          AND deleted_at IS NULL
        """,
        (int(item_id), organization_id),
    ).fetchone()
    if current is None:
        raise PendangCompanyNotFoundError("Company knowledge item was not found.")

    normalized_status = _clean(status, label="Status", maximum=20, required=True)
    if normalized_status not in ITEM_STATUSES:
        raise ValueError("Status must be draft or active.")

    try:
        cursor = db.execute(
            """
            UPDATE organization_knowledge_items
            SET title = ?,
                subtitle = ?,
                body = ?,
                details = ?,
                reference_url = ?,
                scheduled_for = ?,
                status = ?,
                updated_by_user_id = ?,
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
              AND row_version = ?
            """,
            (
                _clean(title, label="Title", maximum=160, required=True),
                _clean(subtitle, label="Subtitle", maximum=240),
                _clean(body, label="Body", maximum=12000),
                _clean(details, label="Details", maximum=8000),
                _clean_url(reference_url),
                _clean_date(scheduled_for),
                normalized_status,
                int(database_actor["id"]),
                int(item_id),
                organization_id,
                expected,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            "An active entry with this title already exists in this Pendang section."
        ) from exc

    if cursor.rowcount != 1:
        raise PendangCompanyConflictError(
            "This entry changed in another session. Reload and try again."
        )

    row = db.execute(
        """
        SELECT id, organization_id, item_type, title, subtitle, body, details,
               reference_url, scheduled_for, status, row_version,
               created_by_user_id, updated_by_user_id, created_at, updated_at
        FROM organization_knowledge_items
        WHERE id = ? AND organization_id = ?
        """,
        (int(item_id), organization_id),
    ).fetchone()
    return dict(row)


def archive_knowledge_item(
    db: sqlite3.Connection,
    actor: Mapping[str, Any],
    item_id: int,
    *,
    expected_row_version: Any,
) -> None:
    database_actor, organization_id = require_manage_authority(db, actor)
    expected = _positive_version(expected_row_version)
    current = db.execute(
        """
        SELECT id
        FROM organization_knowledge_items
        WHERE id = ?
          AND organization_id = ?
          AND deleted_at IS NULL
        """,
        (int(item_id), organization_id),
    ).fetchone()
    if current is None:
        raise PendangCompanyNotFoundError("Company knowledge item was not found.")

    cursor = db.execute(
        """
        UPDATE organization_knowledge_items
        SET deleted_at = CURRENT_TIMESTAMP,
            updated_by_user_id = ?,
            row_version = row_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND organization_id = ?
          AND deleted_at IS NULL
          AND row_version = ?
        """,
        (int(database_actor["id"]), int(item_id), organization_id, expected),
    )
    if cursor.rowcount != 1:
        raise PendangCompanyConflictError(
            "This entry changed in another session. Reload and try again."
        )
