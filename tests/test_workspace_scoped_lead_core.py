from __future__ import annotations

import csv
import io

import pytest

from app import database
from app.services.lead_csv_import import preview_leads_from_csv
from app.services.leads import (
    create_lead,
    delete_lead,
    get_crm_dashboard_metrics,
    get_lead,
    list_leads,
    update_lead_next_action,
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _initialize(tmp_path, monkeypatch):
    database_path = tmp_path / "workspace-core.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()
    return database_path


def _organization_ids(db):
    rows = db.execute(
        "SELECT id, slug FROM organizations ORDER BY slug"
    ).fetchall()
    return {row["slug"]: int(row["id"]) for row in rows}


def _lead_kwargs(*, company: str = "Acme Analytics") -> dict[str, object]:
    return {
        "company": company,
        "contact_person": "Alex Buyer",
        "job_title": "Operations Director",
        "source": "LinkedIn",
        "source_url": "https://example.com/acme",
        "problem_opportunity": "Manual weekly reporting",
        "why_mark_fits": "Power BI and automation experience",
        "pipeline_status": "new",
        "priority": "high",
        "next_action": "Send tailored introduction",
        "next_action_due_date": "2026-08-10",
        "notes": "Workspace-scope test",
    }


def _csv_bytes() -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "Company",
            "Contact person",
            "Job title",
            "Source",
            "Source link",
            "Problem or opportunity",
            "Why Mark fits",
            "Pipeline status",
            "Priority",
            "Next action",
            "Due date",
            "Notes",
        ]
    )
    writer.writerow(
        [
            "Acme Analytics",
            "Alex Buyer",
            "Operations Director",
            "LinkedIn",
            "https://example.com/acme",
            "Manual weekly reporting",
            "Power BI and automation experience",
            "new",
            "high",
            "Send tailored introduction",
            "2026-08-10",
            "Workspace-scope test",
        ]
    )
    return stream.getvalue().encode("utf-8")


def test_same_semantic_lead_can_exist_once_per_workspace(tmp_path, monkeypatch):
    _initialize(tmp_path, monkeypatch)

    with database.get_db() as db:
        organizations = _organization_ids(db)
        mark = create_lead(
            db,
            **_lead_kwargs(),
            request_key="workspace:mark:acme",
            organization_id=organizations["mark-agency"],
        )
        pendang = create_lead(
            db,
            **_lead_kwargs(),
            request_key="workspace:pendang:acme",
            organization_id=organizations["pendang"],
        )
        duplicate = create_lead(
            db,
            **_lead_kwargs(),
            request_key="workspace:pendang:acme:retry",
            organization_id=organizations["pendang"],
        )

        assert mark.created is True
        assert pendang.created is True
        assert mark.lead["id"] != pendang.lead["id"]
        assert mark.lead["dedupe_key"] == pendang.lead["dedupe_key"]
        assert duplicate.created is False
        assert duplicate.lead["id"] == pendang.lead["id"]


def test_core_reads_metrics_updates_and_delete_are_workspace_scoped(
    tmp_path,
    monkeypatch,
):
    _initialize(tmp_path, monkeypatch)

    with database.get_db() as db:
        organizations = _organization_ids(db)
        mark_id = organizations["mark-agency"]
        pendang_id = organizations["pendang"]
        mark = create_lead(
            db,
            **_lead_kwargs(company="MARK Lead"),
            request_key="workspace:mark:lead",
            organization_id=mark_id,
        ).lead
        pendang = create_lead(
            db,
            **_lead_kwargs(company="Pendang Lead"),
            request_key="workspace:pendang:lead",
            organization_id=pendang_id,
        ).lead

        assert get_lead(db, int(mark["id"]), organization_id=mark_id) is not None
        assert get_lead(db, int(mark["id"]), organization_id=pendang_id) is None
        assert get_lead(db, int(pendang["id"]), organization_id=mark_id) is None

        assert [row["company"] for row in list_leads(db, organization_id=mark_id)] == [
            "MARK Lead"
        ]
        assert [
            row["company"] for row in list_leads(db, organization_id=pendang_id)
        ] == ["Pendang Lead"]
        assert get_crm_dashboard_metrics(db, organization_id=mark_id)[
            "total_leads"
        ] == 1
        assert get_crm_dashboard_metrics(db, organization_id=pendang_id)[
            "total_leads"
        ] == 1

        with pytest.raises(ValueError, match="Lead not found"):
            update_lead_next_action(
                db,
                int(mark["id"]),
                next_action="Should not cross workspace",
                organization_id=pendang_id,
            )
        with pytest.raises(ValueError, match="Lead not found"):
            delete_lead(
                db,
                int(mark["id"]),
                confirmed=True,
                organization_id=pendang_id,
            )

        reloaded = get_lead(db, int(mark["id"]), organization_id=mark_id)
        assert reloaded["next_action"] == "Send tailored introduction"
        assert reloaded["deleted_at"] is None


def test_global_request_key_never_returns_another_workspace_lead(
    tmp_path,
    monkeypatch,
):
    _initialize(tmp_path, monkeypatch)

    with database.get_db() as db:
        organizations = _organization_ids(db)
        create_lead(
            db,
            **_lead_kwargs(company="Request Key MARK"),
            request_key="global-request-key",
            organization_id=organizations["mark-agency"],
        )

        with pytest.raises(ValueError, match="Request key was already used"):
            create_lead(
                db,
                **_lead_kwargs(company="Request Key Pendang"),
                request_key="global-request-key",
                organization_id=organizations["pendang"],
            )

        assert list_leads(
            db,
            organization_id=organizations["pendang"],
        ) == []


def test_csv_duplicate_preview_is_isolated_by_workspace(tmp_path, monkeypatch):
    _initialize(tmp_path, monkeypatch)
    content = _csv_bytes()

    with database.get_db() as db:
        organizations = _organization_ids(db)
        create_lead(
            db,
            **_lead_kwargs(),
            request_key="csv-mark-existing",
            organization_id=organizations["mark-agency"],
        )

        mark_preview = preview_leads_from_csv(
            db,
            content,
            organization_id=organizations["mark-agency"],
        )
        pendang_preview = preview_leads_from_csv(
            db,
            content,
            organization_id=organizations["pendang"],
        )

        assert mark_preview.duplicate_count == 1
        assert mark_preview.valid_count == 0
        assert mark_preview.rows[0].status == "duplicate_existing"
        assert pendang_preview.duplicate_count == 0
        assert pendang_preview.valid_count == 1
        assert pendang_preview.rows[0].status == "valid"


def test_legacy_global_dedupe_index_upgrades_idempotently(tmp_path, monkeypatch):
    database_path = _initialize(tmp_path, monkeypatch)

    with database.get_db() as db:
        db.execute("DROP INDEX idx_leads_active_dedupe_key")
        db.execute(
            """
            CREATE UNIQUE INDEX idx_leads_active_dedupe_key
            ON leads(dedupe_key)
            WHERE deleted_at IS NULL
            """
        )

    database.init_db()
    database.init_db()

    with database.get_db() as db:
        columns = [
            row["name"]
            for row in db.execute(
                "PRAGMA index_info(idx_leads_active_dedupe_key)"
            ).fetchall()
        ]
        assert columns == ["organization_id", "dedupe_key"]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
