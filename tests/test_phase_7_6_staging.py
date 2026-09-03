from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app import database
from app.services.leads import create_lead
from tools.verify_phase_7_release import VerificationFailure, run_rehearsal


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DB_PATH", path)
    monkeypatch.setenv("MARK_OS_USERNAME", "release-owner")
    monkeypatch.setenv("MARK_OS_PASSWORD", "release-password-123")
    database.init_db()
    with database.get_db() as db:
        owner = db.execute("SELECT * FROM users WHERE role = 'owner'").fetchone()
        organization_id = db.execute(
            "SELECT id FROM organizations WHERE slug = 'mark-agency'"
        ).fetchone()[0]
        create_lead(
            db,
            organization_id=organization_id,
            created_by_user_id=owner["id"],
            assigned_to_user_id=owner["id"],
            company="Staging Preservation Co",
            contact_person="Buyer",
            source="Referral",
            problem_opportunity="Needs safe releases",
            why_mark_fits="MARK OS has a verifier",
            next_action="Rehearse",
        )


def test_phase_7_rehearsal_is_idempotent_preserving_and_rollback_ready(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.sqlite3"
    _source(source, monkeypatch)
    source_hash = _sha256(source)
    result = run_rehearsal(
        source,
        tmp_path / "evidence",
        release_commit="HEAD",
        last_known_good_commit="HEAD",
        drill_label="automated-test",
    )
    report = result["report"]
    assert report["status"] == "passed"
    assert report["source_preserved"] is True
    assert _sha256(source) == source_hash
    assert report["schema"]["quick_check"] == "ok"
    assert report["schema"]["foreign_key_errors"] == 0
    assert report["health"]["status_code"] == 200
    assert report["preserved_rows"]["leads"] == 1
    assert report["idempotent_rows"]["leads"] == 1
    assert report["rollback_backup"]["backup_path"] != str(source)
    assert all(value is False for value in report["manual_release_gates"].values())
    persisted = json.loads(Path(result["report_path"]).read_text())
    assert persisted["last_known_good_commit"] == report["last_known_good_commit"]


def test_release_evidence_must_be_outside_git(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    _source(source, monkeypatch)
    with pytest.raises(VerificationFailure, match="outside Git"):
        run_rehearsal(
            source,
            Path(__file__).resolve().parents[1] / ".phase-7-evidence",
            release_commit="HEAD",
            last_known_good_commit="HEAD",
        )
