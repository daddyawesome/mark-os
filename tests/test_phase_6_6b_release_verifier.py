from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from app import database
from app.services.leads import create_lead
from tools.verify_phase_6_6b_release import (
    ACCEPTANCE_TEST_FILES,
    VerificationFailure,
    _compare_before_after,
    _verify_pendang_company_seed,
    _verify_phase_schema,
    run_rehearsal,
)


REQUIRED_ACCEPTANCE_FILES = {
    "tests/test_organization_migrations.py",
    "tests/test_workspace_scoped_lead_core.py",
    "tests/test_workspace_scoped_crm_workflows.py",
    "tests/test_pendang_workspace_authority.py",
    "tests/test_pendang_company_workspace.py",
    "tests/test_pendang_founder_plan_surface.py",
    "tests/test_pendang_launch_surface.py",
    "tests/test_lead_optimistic_edit_protection.py",
    "tests/test_follow_up_command_center_acceptance.py",
    "tests/test_lead_contacted_transition.py",
    "tests/test_lead_csv_import.py",
    "tests/test_relationship_manager.py",
    "tests/test_phase_6_1_security_acceptance.py",
    "tests/test_application.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_rehearsal_source(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "DB_PATH", path)
    monkeypatch.setenv("MARK_OS_USERNAME", "release-owner")
    monkeypatch.setenv("MARK_OS_PASSWORD", "release-owner-password")
    database.init_db()

    with database.get_db() as db:
        owner = db.execute(
            "SELECT * FROM users WHERE role='owner' ORDER BY id LIMIT 1"
        ).fetchone()
        assert owner is not None
        create_lead(
            db,
            organization_id=db.execute(
                "SELECT id FROM organizations WHERE slug='mark-agency'"
            ).fetchone()[0],
            created_by_user_id=owner["id"],
            assigned_to_user_id=owner["id"],
            company="Acceptance Source Co",
            contact_person="Release Contact",
            job_title="Operations",
            source="Referral",
            source_url="https://example.test/release",
            problem_opportunity="Needs reporting cleanup",
            why_mark_fits="BI and automation fit",
            pipeline_status="new",
            priority="high",
            next_action="Review source data",
            next_action_due_date="2026-08-10",
            notes="release rehearsal fixture",
        )


def test_acceptance_gate_covers_every_phase_6_6b_risk_area():
    assert REQUIRED_ACCEPTANCE_FILES.issubset(set(ACCEPTANCE_TEST_FILES))


def test_release_rehearsal_never_mutates_source_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source.sqlite3"
    _create_rehearsal_source(source, monkeypatch)
    original_hash = _sha256(source)

    result = run_rehearsal(
        source,
        tmp_path / "evidence",
        run_tests=False,
    )

    assert result["report"]["status"] == "passed"
    assert _sha256(source) == original_hash
    assert Path(result["rehearsal_database"]).exists()
    assert Path(result["backup_path"]).exists()

    schema = result["report"]["schema_verification"]
    assert "mark-agency" in schema["organizations"]
    assert "pendang" in schema["organizations"]
    assert schema["busy_timeout_ms"] > 0
    assert schema["journal_mode"] == "wal"
    assert "organization_id" in schema["lead_columns"]
    assert "row_version" in schema["lead_columns"]
    assert "organization_id, dedupe_key" in schema["workspace_dedupe_index_sql"]
    assert schema["pendang_company"]["profile_count"] == 1
    assert schema["pendang_company"]["seeded_service_count"] == 4
    assert schema["pendang_company"]["mark_agency_profile_count"] == 0
    assert schema["pendang_company"]["mark_agency_knowledge_item_count"] == 0

    before = result["report"]["before_migration"]
    assert before["organization_rows"]
    assert before["lead_rows"][0]["organization_id"]
    assert result["report"]["double_initialization"]["status"] == "passed"

    manual = result["report"]["manual_release_gates"]
    assert manual
    assert all(value is False for value in manual.values())


def test_preservation_check_rejects_a_changed_existing_lead():
    before = {
        "lead_rows": [{"id": 1, "quest_id": 7, "company": "Before"}],
        "activity_rows": [{"id": 3, "lead_id": 1}],
        "table_counts": {"leads": 1, "lead_activities": 1, "tasks": 1},
    }
    after = {
        "lead_rows": [{"id": 1, "quest_id": 7, "company": "After"}],
        "activity_rows": [{"id": 3, "lead_id": 1}],
        "table_counts": {"leads": 1, "lead_activities": 1, "tasks": 1},
    }

    with pytest.raises(VerificationFailure, match="changed existing lead"):
        _compare_before_after(before, after)


def test_phase_6_6c_schema_verification_rejects_missing_company_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "missing-company-table.sqlite3"
    _create_rehearsal_source(source, monkeypatch)

    with sqlite3.connect(source) as db:
        db.execute("DROP TABLE organization_knowledge_items")

    with pytest.raises(VerificationFailure, match="organization_knowledge_items"):
        _verify_phase_schema(source)


def test_phase_6_6c_seed_verification_rejects_duplicate_services_and_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "duplicate-pendang-seed.sqlite3"
    _create_rehearsal_source(source, monkeypatch)

    with sqlite3.connect(source) as db:
        db.row_factory = sqlite3.Row
        pendang_id = int(
            db.execute("SELECT id FROM organizations WHERE slug = 'pendang'").fetchone()[0]
        )
        mark_agency_id = int(
            db.execute("SELECT id FROM organizations WHERE slug = 'mark-agency'").fetchone()[0]
        )
        db.execute("DROP INDEX uq_organization_knowledge_active_title")
        db.execute(
            """
            INSERT INTO organization_knowledge_items (
                organization_id, item_type, title, body, status
            )
            SELECT organization_id, item_type, title, body, status
            FROM organization_knowledge_items
            WHERE organization_id = ? AND item_type = 'service'
            LIMIT 1
            """,
            (pendang_id,),
        )

        with pytest.raises(VerificationFailure, match="missing or duplicated"):
            _verify_pendang_company_seed(
                db,
                pendang_id=pendang_id,
                mark_agency_id=mark_agency_id,
                profile_count=1,
            )

        with pytest.raises(VerificationFailure, match="exactly one company profile"):
            _verify_pendang_company_seed(
                db,
                pendang_id=pendang_id,
                mark_agency_id=mark_agency_id,
                profile_count=2,
            )


def test_phase_6_6c_seed_verification_rejects_mark_agency_contamination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "mark-agency-contamination.sqlite3"
    _create_rehearsal_source(source, monkeypatch)

    with sqlite3.connect(source) as db:
        db.row_factory = sqlite3.Row
        pendang_id = int(
            db.execute("SELECT id FROM organizations WHERE slug = 'pendang'").fetchone()[0]
        )
        mark_agency_id = int(
            db.execute("SELECT id FROM organizations WHERE slug = 'mark-agency'").fetchone()[0]
        )
        db.execute(
            "INSERT INTO organization_company_profiles (organization_id) VALUES (?)",
            (mark_agency_id,),
        )

        with pytest.raises(VerificationFailure, match="MARK Agency"):
            _verify_pendang_company_seed(
                db,
                pendang_id=pendang_id,
                mark_agency_id=mark_agency_id,
                profile_count=1,
            )
