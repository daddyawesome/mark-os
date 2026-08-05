from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import database
from app.services.lead_pipeline_workflow import (
    approve_outreach,
    change_pipeline_stage,
)
from app.services.lead_research_workflow import (
    review_research,
    submit_research_for_review,
    update_research_details,
)
from app.services.leads import create_lead
from app.services.team_users import (
    create_lead_sourcer,
    get_primary_owner_id,
)


REQUIRED_LEAD_COLUMNS = {
    "created_by_user_id",
    "assigned_to_user_id",
    "researched_by_user_id",
    "research_status",
    "submitted_for_review_at",
    "reviewed_by_user_id",
    "reviewed_at",
    "review_notes",
    "outreach_approved_by_user_id",
    "outreach_approved_at",
}

REQUIRED_RESEARCH_INDEXES = {
    "idx_leads_research_queue",
    "idx_leads_researcher_activity",
}

VALID_RESEARCH_STATUSES = {
    "draft",
    "researching",
    "ready_for_review",
    "changes_requested",
    "approved",
    "rejected",
}


class VerificationFailure(RuntimeError):
    pass


def _utc_stamp() -> str:
    return datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _online_backup(
    source_path: Path,
    destination_path: Path,
) -> None:
    destination_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    source = _connect(source_path)
    destination = _connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def _integrity_report(
    path: Path,
) -> dict[str, Any]:
    db = _connect(path)
    try:
        quick_check = db.execute(
            "PRAGMA quick_check"
        ).fetchone()[0]
        foreign_keys = [
            tuple(row)
            for row in db.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
        ]
        return {
            "quick_check": quick_check,
            "foreign_key_errors": foreign_keys,
        }
    finally:
        db.close()


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _assert_clean_git(
    allow_dirty: bool,
) -> dict[str, str]:
    status = _git_value(
        "status",
        "--porcelain",
    )
    if status and not allow_dirty:
        raise VerificationFailure(
            "The Git working tree is not clean. "
            "Commit the Phase 6.1 files first, or "
            "rerun with --allow-dirty for a local "
            "pre-commit check."
        )
    return {
        "branch": _git_value(
            "branch",
            "--show-current",
        ),
        "commit": _git_value(
            "rev-parse",
            "HEAD",
        ),
        "status": status,
    }


def _schema_and_data_checks(
    path: Path,
) -> dict[str, Any]:
    db = _connect(path)
    try:
        lead_columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(leads)"
            ).fetchall()
        }
        missing_columns = sorted(
            REQUIRED_LEAD_COLUMNS - lead_columns
        )
        if missing_columns:
            raise VerificationFailure(
                "Missing Phase 6.1 lead columns: "
                + ", ".join(missing_columns)
            )

        lead_indexes = {
            row["name"]
            for row in db.execute(
                "PRAGMA index_list(leads)"
            ).fetchall()
        }
        missing_indexes = sorted(
            REQUIRED_RESEARCH_INDEXES
            - lead_indexes
        )
        if missing_indexes:
            raise VerificationFailure(
                "Missing Phase 6.1 lead indexes: "
                + ", ".join(missing_indexes)
            )

        bad_statuses = [
            row["research_status"]
            for row in db.execute(
                """
                SELECT DISTINCT research_status
                FROM leads
                WHERE research_status
                    NOT IN (
                        'draft',
                        'researching',
                        'ready_for_review',
                        'changes_requested',
                        'approved',
                        'rejected'
                    )
                """
            ).fetchall()
        ]
        if bad_statuses:
            raise VerificationFailure(
                "Unsupported research statuses found: "
                + ", ".join(
                    str(value)
                    for value in bad_statuses
                )
            )

        unpaired_outreach = db.execute(
            """
            SELECT COUNT(*)
            FROM leads
            WHERE (
                outreach_approved_by_user_id IS NULL
            ) != (
                outreach_approved_at IS NULL
            )
            """
        ).fetchone()[0]
        if unpaired_outreach:
            raise VerificationFailure(
                "Found lead rows with only half of the "
                "outreach approval pair populated."
            )

        invalid_review_ready = db.execute(
            """
            SELECT COUNT(*)
            FROM leads
            WHERE research_status = 'ready_for_review'
              AND submitted_for_review_at IS NULL
            """
        ).fetchone()[0]
        if invalid_review_ready:
            raise VerificationFailure(
                "Found ready-for-review leads without "
                "a submission timestamp."
            )

        invalid_decisions = db.execute(
            """
            SELECT COUNT(*)
            FROM leads
            WHERE research_status
                IN (
                    'changes_requested',
                    'approved',
                    'rejected'
                )
              AND (
                    reviewed_by_user_id IS NULL
                    OR reviewed_at IS NULL
              )
            """
        ).fetchone()[0]
        if invalid_decisions:
            raise VerificationFailure(
                "Found reviewed leads without reviewer "
                "or review timestamp."
            )

        invalid_outreach_status = db.execute(
            """
            SELECT COUNT(*)
            FROM leads
            WHERE outreach_approved_at IS NOT NULL
              AND research_status != 'approved'
            """
        ).fetchone()[0]
        if invalid_outreach_status:
            raise VerificationFailure(
                "Found outreach approval on research "
                "that is not approved."
            )

        counts = {
            "users": db.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0],
            "owners": db.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE role = 'owner'
                  AND active = 1
                """
            ).fetchone()[0],
            "lead_researchers": db.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE role = 'lead_sourcer'
                  AND active = 1
                """
            ).fetchone()[0],
            "active_leads": db.execute(
                """
                SELECT COUNT(*)
                FROM leads
                WHERE deleted_at IS NULL
                """
            ).fetchone()[0],
            "deleted_leads": db.execute(
                """
                SELECT COUNT(*)
                FROM leads
                WHERE deleted_at IS NOT NULL
                """
            ).fetchone()[0],
            "ready_for_review": db.execute(
                """
                SELECT COUNT(*)
                FROM leads
                WHERE deleted_at IS NULL
                  AND research_status
                      = 'ready_for_review'
                """
            ).fetchone()[0],
            "changes_requested": db.execute(
                """
                SELECT COUNT(*)
                FROM leads
                WHERE deleted_at IS NULL
                  AND research_status
                      = 'changes_requested'
                """
            ).fetchone()[0],
            "approved_research": db.execute(
                """
                SELECT COUNT(*)
                FROM leads
                WHERE deleted_at IS NULL
                  AND research_status = 'approved'
                """
            ).fetchone()[0],
        }
        return {
            "missing_columns": missing_columns,
            "missing_indexes": missing_indexes,
            "valid_research_statuses": sorted(
                VALID_RESEARCH_STATUSES
            ),
            "counts": counts,
        }
    finally:
        db.close()


def _game_state_snapshot(db):
    return [
        tuple(row)
        for row in db.execute(
            """
            SELECT
                id,
                user_id,
                level,
                xp_total,
                xp_into_level,
                last_level_up_at
            FROM game_state
            ORDER BY id
            """
        ).fetchall()
    ]


def _run_workflow_canary(
    staging_path: Path,
) -> dict[str, Any]:
    database.DB_PATH = staging_path
    database.init_db()

    unique = _utc_stamp().casefold()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db)
        if owner_id is None:
            raise VerificationFailure(
                "The staging copy has no active Owner."
            )

        owner_row = db.execute(
            """
            SELECT
                id,
                username,
                display_name,
                role
            FROM users
            WHERE id = ?
            """,
            (owner_id,),
        ).fetchone()
        owner = dict(owner_row)

        sourcer_row = create_lead_sourcer(
            db,
            username=(
                "release-canary-"
                + unique[-12:]
            ),
            display_name=(
                "Phase 6.1 Release Canary"
            ),
            password=(
                "release-canary-pass-123"
            ),
            password_confirmation=(
                "release-canary-pass-123"
            ),
        )
        sourcer = dict(sourcer_row)

        xp_before = _game_state_snapshot(db)
        ledger_before = db.execute(
            "SELECT COUNT(*) FROM xp_ledger"
        ).fetchone()[0]

        lead = create_lead(
            db,
            company=(
                "Phase 6.1 Canary "
                + unique
            ),
            contact_person="Release Verifier",
            job_title="Test Contact",
            source="Staging canary",
            source_url="https://example.com/canary",
            problem_opportunity=(
                "Verify the complete Phase 6.1 "
                "workflow on a copied database."
            ),
            why_mark_fits=(
                "This is a non-production staging "
                "verification record."
            ),
            pipeline_status="new",
            priority="low",
            next_action="Run staging verification.",
            next_action_due_date=None,
            notes=(
                "Created by "
                "verify_phase_6_1_release.py."
            ),
            request_key=(
                "phase-6-1-canary-"
                + unique
            ),
            created_by_user_id=sourcer["id"],
            assigned_to_user_id=owner["id"],
        ).lead

        researched = update_research_details(
            db,
            lead["id"],
            actor=sourcer,
            company=lead["company"],
            contact_person=lead["contact_person"],
            job_title=lead["job_title"],
            source=lead["source"],
            source_url=lead["source_url"],
            problem_opportunity=(
                "The copied database needs a safe "
                "end-to-end workflow canary."
            ),
            why_mark_fits=(
                "The canary verifies permissions and "
                "workflow state."
            ),
            next_action=(
                "Submit the staging canary."
            ),
            next_action_due_date=None,
            notes="Canary research complete.",
        )
        submitted = submit_research_for_review(
            db,
            researched["id"],
            actor=sourcer,
        )
        approved = review_research(
            db,
            submitted["id"],
            actor=owner,
            decision="approved",
            review_notes=(
                "Release canary research approved."
            ),
        )
        outreach = approve_outreach(
            db,
            approved["id"],
            actor=owner,
        )
        contacted = change_pipeline_stage(
            db,
            outreach["id"],
            actor=owner,
            pipeline_status="contacted",
        )

        if (
            contacted["research_status"]
            != "approved"
            or contacted["pipeline_status"]
            != "contacted"
            or contacted[
                "outreach_approved_by_user_id"
            ]
            != owner["id"]
        ):
            raise VerificationFailure(
                "The Phase 6.1 workflow canary did "
                "not reach its expected final state."
            )

        if _game_state_snapshot(db) != xp_before:
            raise VerificationFailure(
                "The workflow canary changed "
                "game_state."
            )
        if (
            db.execute(
                "SELECT COUNT(*) FROM xp_ledger"
            ).fetchone()[0]
            != ledger_before
        ):
            raise VerificationFailure(
                "The workflow canary changed "
                "xp_ledger."
            )

        return {
            "owner_id": owner["id"],
            "lead_researcher_id": sourcer["id"],
            "lead_id": contacted["id"],
            "quest_id": contacted["quest_id"],
            "research_status": (
                contacted["research_status"]
            ),
            "pipeline_status": (
                contacted["pipeline_status"]
            ),
            "outreach_approved_at": (
                contacted["outreach_approved_at"]
            ),
            "xp_unchanged": True,
        }


def _health_check(url: str | None):
    if not url:
        return {
            "status": "skipped",
        }

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "MARK-OS-Phase-6.1-Verifier"
            )
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=15,
        ) as response:
            body = response.read().decode(
                "utf-8",
                errors="replace",
            )
            if response.status != 200:
                raise VerificationFailure(
                    "Health endpoint returned "
                    f"HTTP {response.status}."
                )
            return {
                "status": "passed",
                "http_status": response.status,
                "body": body,
            }
    except Exception as exc:
        raise VerificationFailure(
            f"Health check failed: {exc}"
        ) from exc


def _run_tests() -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
        ],
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise VerificationFailure(
            "The full pytest suite failed."
        )
    return {
        "status": "passed",
        "command": (
            f"{sys.executable} -m pytest -q"
        ),
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Verify Phase 6.1 against an online "
            "SQLite backup copy."
        )
    )
    parser.add_argument(
        "--source-db",
        required=True,
        type=Path,
        help=(
            "Existing SQLite database to copy. "
            "The source is never migrated or written."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            ".phase_6_1_release"
        ),
        help=(
            "Directory for the staging copy and "
            "verification report."
        ),
    )
    parser.add_argument(
        "--health-url",
        default=None,
        help=(
            "Optional deployed /health URL to check."
        ),
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help=(
            "Run the complete pytest suite before "
            "marking verification successful."
        ),
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Allow a dirty Git tree for a local "
            "pre-commit verification."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = (
        args.source_db.expanduser().resolve()
    )
    if not source_path.is_file():
        print(
            f"ERROR: source database not found: "
            f"{source_path}",
            file=sys.stderr,
        )
        return 1

    stamp = _utc_stamp()
    run_dir = (
        args.output_dir.expanduser().resolve()
        / stamp
    )
    staging_path = (
        run_dir / "mark_os_staging.db"
    )
    report_path = (
        run_dir
        / "phase_6_1_verification.json"
    )

    report: dict[str, Any] = {
        "phase": "6.1H-I",
        "started_at_utc": stamp,
        "source_database": str(source_path),
        "staging_database": str(staging_path),
        "status": "running",
    }

    try:
        report["git"] = _assert_clean_git(
            args.allow_dirty,
        )

        source_before = _integrity_report(
            source_path,
        )
        if source_before["quick_check"] != "ok":
            raise VerificationFailure(
                "Source database quick_check "
                "did not return ok."
            )
        if source_before[
            "foreign_key_errors"
        ]:
            raise VerificationFailure(
                "Source database has foreign-key "
                "errors."
            )
        report["source_integrity"] = source_before

        _online_backup(
            source_path,
            staging_path,
        )
        report["source_sha256"] = _sha256(
            source_path,
        )
        report["staging_sha256_before"] = (
            _sha256(staging_path)
        )

        staging_before = _integrity_report(
            staging_path,
        )
        if staging_before["quick_check"] != "ok":
            raise VerificationFailure(
                "Staging copy quick_check failed "
                "before initialization."
            )
        if staging_before[
            "foreign_key_errors"
        ]:
            raise VerificationFailure(
                "Staging copy has foreign-key errors "
                "before initialization."
            )
        report[
            "staging_integrity_before"
        ] = staging_before

        database.DB_PATH = staging_path
        database.init_db()

        staging_after_init = _integrity_report(
            staging_path,
        )
        if (
            staging_after_init["quick_check"]
            != "ok"
        ):
            raise VerificationFailure(
                "Staging copy quick_check failed "
                "after initialization."
            )
        if staging_after_init[
            "foreign_key_errors"
        ]:
            raise VerificationFailure(
                "Staging copy has foreign-key errors "
                "after initialization."
            )
        report[
            "staging_integrity_after_init"
        ] = staging_after_init

        report["schema_and_data"] = (
            _schema_and_data_checks(
                staging_path,
            )
        )
        report["workflow_canary"] = (
            _run_workflow_canary(
                staging_path,
            )
        )

        final_integrity = _integrity_report(
            staging_path,
        )
        if final_integrity["quick_check"] != "ok":
            raise VerificationFailure(
                "Staging copy quick_check failed "
                "after the workflow canary."
            )
        if final_integrity[
            "foreign_key_errors"
        ]:
            raise VerificationFailure(
                "Staging copy has foreign-key errors "
                "after the workflow canary."
            )
        report[
            "staging_integrity_final"
        ] = final_integrity

        report["health"] = _health_check(
            args.health_url,
        )
        report["tests"] = (
            _run_tests()
            if args.run_tests
            else {"status": "skipped"}
        )
        report["status"] = "passed"
        report["completed_at_utc"] = (
            _utc_stamp()
        )

    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        report["completed_at_utc"] = (
            _utc_stamp()
        )
        run_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        report_path.write_text(
            json.dumps(
                report,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print(
            f"FAILED: {exc}",
            file=sys.stderr,
        )
        print(
            f"Report: {report_path}",
            file=sys.stderr,
        )
        return 1

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print("Phase 6.1 verification PASSED")
    print(f"Source:  {source_path}")
    print(f"Staging: {staging_path}")
    print(f"Report:  {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
