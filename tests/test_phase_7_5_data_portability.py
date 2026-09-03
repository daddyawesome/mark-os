from __future__ import annotations

import io
import json
import zipfile

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.data_portability import (
    build_portability_package,
    package_json,
    package_zip,
    table_csv,
)
from app.services.leads import create_lead
from app.services.team_users import create_lead_sourcer


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _actor(user, organization_id):
    return {
        **dict(user),
        "current_workspace": {
            "id": organization_id,
            "slug": "mark-agency",
            "name": "MARK Agency",
            "membership_role": "crm_contributor",
        },
    }


def test_staff_export_is_visibility_scoped_and_structurally_excludes_secrets(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "portability.db")
    _configure_owner(monkeypatch)
    database.init_db()
    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        first = create_lead_sourcer(
            db,
            username="first",
            display_name="First",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        second = create_lead_sourcer(
            db,
            username="second",
            display_name="Second",
            password="temporary-pass-456",
            password_confirmation="temporary-pass-456",
        )
        created = []
        for creator, company in ((first, "Visible Export Co"), (second, "Private Export Co")):
            created.append(create_lead(
                db,
                company=company,
                contact_person="Buyer",
                source="Referral",
                problem_opportunity="Needs reporting",
                why_mark_fits="MARK OS can help",
                next_action="Research",
                created_by_user_id=creator["id"],
                assigned_to_user_id=creator["id"],
                organization_id=organization_id,
            ).lead)
        db.execute(
            """
            INSERT INTO proposals (organization_id, lead_id, service_offered)
            VALUES (?, ?, 'Private pricing context')
            """,
            (organization_id, created[0]["id"]),
        )
        package = build_portability_package(db, _actor(first, organization_id))

    rendered = package_json(package).decode()
    assert "Visible Export Co" in rendered
    assert "Private Export Co" not in rendered
    assert "temporary-pass" not in rendered
    assert "password_hash" not in rendered
    assert "auth_sessions" not in package["tables"]
    assert "login_attempts" not in package["tables"]
    assert "security_audit_events" not in package["tables"]
    assert "webhook_intake_tokens" not in package["tables"]
    assert "proposals" not in package["tables"]
    assert "outreach_templates" not in package["tables"]
    assert "Private pricing context" not in rendered


def test_zip_has_json_manifest_and_csv_per_available_table(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "portable-zip.db")
    _configure_owner(monkeypatch)
    database.init_db()
    with database.get_db() as db:
        owner = db.execute("SELECT id, role FROM users WHERE role = 'owner'").fetchone()
        organization_id = organization_id_by_slug(db, "mark-agency")
        package = build_portability_package(db, _actor(owner, organization_id))

    with zipfile.ZipFile(io.BytesIO(package_zip(package))) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    assert "mark-os-export.json" in names
    assert "csv/account.csv" in names
    assert "csv/leads.csv" in names
    assert set(manifest["tables"]) == set(package["tables"])


def test_csv_neutralizes_spreadsheet_formula_prefixes():
    rendered = table_csv([{"id": 1, "title": "  =HYPERLINK(\"bad\")"}]).decode(
        "utf-8-sig"
    )
    assert "'  =HYPERLINK" in rendered
