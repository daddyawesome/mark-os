from __future__ import annotations

import csv
import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from typing import Any, Mapping

from app.services.access_control import has_crm_owner_authority, is_owner
from app.services.lead_work_queues import list_visible_leads


PERSONAL_TABLES = (
    "profile", "goals", "projects", "checkins", "directions", "game_state",
    "game_history", "tasks", "quest_updates", "xp_ledger", "memories",
    "timeline_events", "chat_sessions", "chat_messages", "agent_runs", "agent_steps",
)
SENSITIVE_KEYS = frozenset(
    {
        "password_hash", "session_version", "token", "token_hash", "secret",
        "webhook_url", "api_key", "authorization",
    }
)


def _rows(db: sqlite3.Connection, sql: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(sql, parameters).fetchall()]


def _by_ids(
    db: sqlite3.Connection,
    table: str,
    column: str,
    values: list[int],
) -> list[dict[str, Any]]:
    if not values:
        return []
    placeholders = ",".join("?" for _ in values)
    return _rows(
        db,
        f"SELECT * FROM {table} WHERE {column} IN ({placeholders}) ORDER BY id",
        tuple(values),
    )


def build_portability_package(
    db: sqlite3.Connection,
    user: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an allowlisted export; authentication and secret tables are absent."""
    user_id = int(user["id"])
    role = str(user.get("role") or "")
    account = db.execute(
        """
        SELECT id, username, display_name, role, active, must_change_password,
               last_login_at, created_at, updated_at
        FROM users WHERE id = ? AND active = 1
        """,
        (user_id,),
    ).fetchone()
    if account is None:
        raise ValueError("An active account is required for export.")

    tables: dict[str, list[dict[str, Any]]] = {"account": [dict(account)]}
    if role in {"owner", "member"}:
        for table in PERSONAL_TABLES:
            tables[table] = _rows(
                db, f"SELECT * FROM {table} WHERE user_id = ? ORDER BY id", (user_id,)
            )

    workspace = user.get("current_workspace")
    if role in {"owner", "lead_sourcer", "relationship_manager"} and isinstance(
        workspace, Mapping
    ):
        organization_id = int(workspace["id"])
        organization = db.execute(
            "SELECT id, slug, name, created_at, updated_at FROM organizations WHERE id = ?",
            (organization_id,),
        ).fetchone()
        tables["organization"] = [dict(organization)] if organization else []
        visible = list_visible_leads(db, user, organization_id=organization_id)
        lead_ids = [int(row["id"]) for row in visible]
        tables["leads"] = _by_ids(db, "leads", "id", lead_ids)
        tables["lead_activities"] = _by_ids(
            db, "lead_activities", "lead_id", lead_ids
        )
        if role in {"owner", "relationship_manager"}:
            tables["proposals"] = _by_ids(
                db, "proposals", "lead_id", lead_ids
            )

        if has_crm_owner_authority(user):
            tables["outreach_templates"] = _rows(
                db,
                "SELECT * FROM outreach_templates WHERE organization_id = ? ORDER BY id",
                (organization_id,),
            )
            tables["organization_company_profiles"] = _rows(
                db,
                "SELECT * FROM organization_company_profiles WHERE organization_id = ?",
                (organization_id,),
            )
            tables["organization_knowledge_items"] = _rows(
                db,
                "SELECT * FROM organization_knowledge_items WHERE organization_id = ? ORDER BY id",
                (organization_id,),
            )
            tables["organization_clients"] = _rows(
                db,
                "SELECT * FROM organization_clients WHERE organization_id = ? ORDER BY id",
                (organization_id,),
            )
            client_ids = [row["id"] for row in tables["organization_clients"]]
            tables["client_engagements"] = _by_ids(
                db, "client_engagements", "client_id", client_ids
            )
            engagement_ids = [row["id"] for row in tables["client_engagements"]]
            tables["engagement_items"] = _by_ids(
                db, "engagement_items", "engagement_id", engagement_ids
            )
            if is_owner(user):
                for table in (
                    "billing_arrangements", "invoices", "engagement_costs"
                ):
                    tables[table] = _by_ids(
                        db, table, "engagement_id", engagement_ids
                    )
                invoice_ids = [row["id"] for row in tables["invoices"]]
                tables["payments"] = _by_ids(
                    db, "payments", "invoice_id", invoice_ids
                )
        elif role == "relationship_manager":
            tables["outreach_templates"] = _rows(
                db,
                """
                SELECT * FROM outreach_templates
                WHERE organization_id = ? AND approved = 1 AND active = 1
                ORDER BY id
                """,
                (organization_id,),
            )

    for rows in tables.values():
        for row in rows:
            if SENSITIVE_KEYS.intersection(row):
                raise RuntimeError("Sensitive field entered the portability allowlist.")
    return {
        "schema_version": 1,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "tables": tables,
    }


def _safe_csv_value(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def table_csv(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    fieldnames = list(rows[0]) if rows else ["id"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _safe_csv_value(value) for key, value in row.items()})
    return output.getvalue().encode("utf-8-sig")


def package_json(package: Mapping[str, Any]) -> bytes:
    return json.dumps(package, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def package_zip(package: Mapping[str, Any]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mark-os-export.json", package_json(package))
        tables = package["tables"]
        for table in sorted(tables):
            archive.writestr(f"csv/{table}.csv", table_csv(tables[table]))
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": package["schema_version"],
                    "exported_at_utc": package["exported_at_utc"],
                    "tables": sorted(tables),
                },
                indent=2,
            ),
        )
    return output.getvalue()
