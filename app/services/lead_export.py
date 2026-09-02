from __future__ import annotations

import csv
import io
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from app.services.lead_work_queues import list_visible_leads


Record = Mapping[str, Any] | sqlite3.Row

EXPORT_COLUMNS = (
    "id",
    "company",
    "contact_person",
    "job_title",
    "source",
    "source_url",
    "problem_opportunity",
    "why_mark_fits",
    "pipeline_status",
    "priority",
    "research_status",
    "next_action",
    "next_action_due_date",
    "notes",
    "created_by_name",
    "assigned_to_name",
    "researched_by_name",
    "business_development_owner_name",
    "created_at",
    "updated_at",
)

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _csv_safe(value: Any) -> str:
    """Neutralize spreadsheet formula injection in exported text cells."""
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _export_rows(
    db: sqlite3.Connection,
    user: Record | None,
    *,
    organization_id: int | None,
    approved_only: bool,
) -> list[dict[str, Any]]:
    leads = list_visible_leads(
        db,
        user,
        organization_id=organization_id,
    )
    rows = [dict(lead) for lead in leads]
    if approved_only:
        rows = [
            row
            for row in rows
            if str(row.get("research_status") or "").casefold()
            == "approved"
        ]
    return rows


def export_leads_csv(
    db: sqlite3.Connection,
    user: Record | None,
    *,
    organization_id: int | None = None,
    approved_only: bool = False,
) -> bytes:
    """Export the actor's visible leads as CSV, scoped by CRM permissions.

    Uses the same organization- and role-based visibility as the CRM
    dashboard, so a Lead Sourcer or Relationship Manager can never export
    leads they are not otherwise permitted to see.
    """
    rows = _export_rows(
        db,
        user,
        organization_id=organization_id,
        approved_only=approved_only,
    )
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        writer.writerow(
            _csv_safe(row.get(column)) for column in EXPORT_COLUMNS
        )
    return stream.getvalue().encode("utf-8-sig")


def export_leads_json(
    db: sqlite3.Connection,
    user: Record | None,
    *,
    organization_id: int | None = None,
    approved_only: bool = False,
) -> bytes:
    """Export the actor's visible leads as JSON, scoped by CRM permissions."""
    rows = _export_rows(
        db,
        user,
        organization_id=organization_id,
        approved_only=approved_only,
    )
    payload = [
        {column: row.get(column) for column in EXPORT_COLUMNS}
        for row in rows
    ]
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
