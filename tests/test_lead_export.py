from __future__ import annotations

import csv
import io
import json

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.lead_export import export_leads_csv, export_leads_json
from app.services.leads import create_lead
from app.services.team_users import create_lead_sourcer


OWNER = {"id": 1, "username": "mark", "role": "owner"}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _create_lead(db, *, organization_id, company, research_status="draft"):
    result = create_lead(
        db,
        company=company,
        contact_person="Dana Buyer",
        job_title="Founder",
        source="LinkedIn",
        source_url="https://example.com/" + company.casefold().replace(" ", "-"),
        problem_opportunity="Reporting is manual.",
        why_mark_fits="Mark can automate reporting.",
        pipeline_status="new",
        priority="medium",
        next_action="Complete research.",
        next_action_due_date="2026-08-10",
        notes="Initial note.",
        organization_id=organization_id,
    ).lead
    if research_status != "draft":
        db.execute(
            "UPDATE leads SET research_status = ? WHERE id = ?",
            (research_status, result["id"]),
        )
    return result


def test_csv_export_contains_only_visible_leads(tmp_path, monkeypatch):
    path = tmp_path / "export-csv.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        sourcer = create_lead_sourcer(
            db,
            username="researcher-one",
            display_name="Researcher One",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        own_lead = _create_lead(
            db,
            organization_id=organization_id,
            company="Owned By Researcher",
        )
        db.execute(
            "UPDATE leads SET assigned_to_user_id = ? WHERE id = ?",
            (sourcer["id"], own_lead["id"]),
        )
        _create_lead(
            db,
            organization_id=organization_id,
            company="Not Visible To Researcher",
        )

        content = export_leads_csv(
            db,
            {"id": sourcer["id"], "role": "lead_sourcer"},
            organization_id=organization_id,
        )

    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    companies = [row[1] for row in rows[1:]]
    assert companies == ["Owned By Researcher"]


def test_json_export_matches_csv_scope_and_is_valid_json(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "export-json.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        _create_lead(
            db,
            organization_id=organization_id,
            company="Alpha Analytics",
        )
        _create_lead(
            db,
            organization_id=organization_id,
            company="Beta Insights",
        )

        content = export_leads_json(
            db,
            OWNER,
            organization_id=organization_id,
        )

    payload = json.loads(content.decode("utf-8"))
    assert {row["company"] for row in payload} == {
        "Alpha Analytics",
        "Beta Insights",
    }


def test_approved_only_export_excludes_unapproved_leads(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "export-approved.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        _create_lead(
            db,
            organization_id=organization_id,
            company="Approved Co",
            research_status="approved",
        )
        _create_lead(
            db,
            organization_id=organization_id,
            company="Still Drafting Co",
        )

        content = export_leads_json(
            db,
            OWNER,
            organization_id=organization_id,
            approved_only=True,
        )

    payload = json.loads(content.decode("utf-8"))
    assert [row["company"] for row in payload] == ["Approved Co"]


def test_csv_export_neutralizes_formula_injection(tmp_path, monkeypatch):
    path = tmp_path / "export-formula.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        create_lead(
            db,
            company="=cmd|'/c calc'!A1",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="LinkedIn",
            source_url="https://example.com/formula",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="new",
            priority="medium",
            next_action="Complete research.",
            next_action_due_date="2026-08-10",
            notes="Initial note.",
            organization_id=organization_id,
        )

        content = export_leads_csv(
            db,
            OWNER,
            organization_id=organization_id,
        )

    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    assert rows[1][1] == "'=cmd|'/c calc'!A1"
