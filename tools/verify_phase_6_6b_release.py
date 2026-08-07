from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import database
from app.services.database_backup import (
    create_sqlite_backup,
    restore_sqlite_backup,
    verify_backup_manifest,
    verify_sqlite_database,
)


ACCEPTANCE_TEST_FILES = (
    "tests/test_organization_migrations.py",
    "tests/test_workspace_scoped_lead_core.py",
    "tests/test_workspace_scoped_crm_workflows.py",
    "tests/test_pendang_workspace_authority.py",
    "tests/test_pendang_launch_surface.py",
    "tests/test_lead_optimistic_edit_protection.py",
    "tests/test_follow_up_command_center_acceptance.py",
    "tests/test_lead_contacted_transition.py",
    "tests/test_lead_csv_import.py",
    "tests/test_relationship_manager.py",
    "tests/test_phase_6_1_security_acceptance.py",
    "tests/test_application.py",
)

LEAD_STABLE_FIELDS = (
    "id",
    "quest_id",
    "created_by_user_id",
    "assigned_to_user_id",
    "request_key",
    "request_fingerprint",
    "dedupe_key",
    "company",
    "contact_person",
    "job_title",
    "source",
    "source_url",
    "problem_opportunity",
    "why_mark_fits",
    "pipeline_status",
    "priority",
    "next_action",
    "next_action_due_date",
    "notes",
    "created_at",
    "updated_at",
    "deleted_at",
    "researched_by_user_id",
    "research_status",
    "submitted_for_review_at",
    "reviewed_by_user_id",
    "reviewed_at",
    "review_notes",
    "outreach_approved_by_user_id",
    "outreach_approved_at",
    "business_development_owner_user_id",
)


class VerificationFailure(RuntimeError):
    pass


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    if not _table_exists(db, table):
        return []
    return [str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})")]


def _table_counts(path: Path) -> dict[str, int]:
    with _connect(path) as db:
        names = [
            str(row["name"])
            for row in db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]
        return {
            name: int(db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            for name in names
        }


def _snapshot_rehearsal_state(path: Path) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "table_counts": _table_counts(path),
        "lead_columns": [],
        "lead_rows": [],
        "activity_rows": [],
        "membership_rows": [],
    }
    with _connect(path) as db:
        lead_columns = _columns(db, "leads")
        snapshot["lead_columns"] = lead_columns
        stable = [field for field in LEAD_STABLE_FIELDS if field in lead_columns]
        if stable:
            select_sql = ", ".join(stable)
            snapshot["lead_rows"] = [
                {field: row[field] for field in stable}
                for row in db.execute(
                    f"SELECT {select_sql} FROM leads ORDER BY id"
                )
            ]
        if _table_exists(db, "lead_activities"):
            activity_columns = _columns(db, "lead_activities")
            wanted = [name for name in ("id", "lead_id") if name in activity_columns]
            if wanted:
                snapshot["activity_rows"] = [
                    {name: row[name] for name in wanted}
                    for row in db.execute(
                        f"SELECT {', '.join(wanted)} FROM lead_activities ORDER BY id"
                    )
                ]
        if _table_exists(db, "organization_memberships"):
            membership_columns = _columns(db, "organization_memberships")
            wanted = [
                name
                for name in (
                    "user_id",
                    "organization_id",
                    "membership_role",
                    "active",
                )
                if name in membership_columns
            ]
            if wanted:
                snapshot["membership_rows"] = [
                    {name: row[name] for name in wanted}
                    for row in db.execute(
                        "SELECT " + ", ".join(wanted)
                        + " FROM organization_memberships "
                        + "ORDER BY user_id, organization_id"
                    )
                ]
    return snapshot


def _run_migrations(rehearsal_path: Path) -> None:
    original = database.DB_PATH
    database.DB_PATH = rehearsal_path
    try:
        database.init_db()
    finally:
        database.DB_PATH = original


def _verify_health(rehearsal_path: Path) -> dict[str, Any]:
    # Call the actual MARK-OS /health route function directly. The release
    # verifier should not require Starlette TestClient/httpx2 just to inspect
    # database readiness. HTTP routing/middleware remains covered by pytest.
    original = database.DB_PATH
    database.DB_PATH = rehearsal_path
    try:
        from app.routes.pages import health

        response = health()
        status_code = int(response.status_code)
        payload = json.loads(response.body.decode("utf-8"))

        if status_code != 200:
            raise VerificationFailure(
                f"Rehearsal /health returned HTTP {status_code}."
            )
        if payload.get("status") != "ok":
            raise VerificationFailure(
                "Rehearsal /health payload did not report status=ok."
            )
        if (
            payload.get("checks", {})
            .get("database", {})
            .get("status")
            != "ok"
        ):
            raise VerificationFailure(
                "Rehearsal /health database check did not report status=ok."
            )

        return {
            "status": "passed",
            "http_status": status_code,
            "payload": payload,
        }
    finally:
        database.DB_PATH = original


def _verify_phase_schema(path: Path) -> dict[str, Any]:
    with _connect(path) as db:
        organizations = {
            str(row["slug"]): {
                "id": int(row["id"]),
                "name": str(row["name"]),
            }
            for row in db.execute(
                "SELECT id, slug, name FROM organizations ORDER BY id"
            )
        }
        for slug in ("mark-agency", "pendang"):
            if slug not in organizations:
                raise VerificationFailure(f"Required workspace missing: {slug}")

        lead_columns = set(_columns(db, "leads"))
        for required in ("organization_id", "row_version"):
            if required not in lead_columns:
                raise VerificationFailure(f"leads.{required} is missing")

        bad_versions = int(
            db.execute("SELECT COUNT(*) FROM leads WHERE row_version < 1").fetchone()[0]
        )
        if bad_versions:
            raise VerificationFailure("One or more leads have invalid row_version")

        null_orgs = int(
            db.execute("SELECT COUNT(*) FROM leads WHERE organization_id IS NULL").fetchone()[0]
        )
        if null_orgs:
            raise VerificationFailure("One or more leads are missing organization_id")

        index = db.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type='index' AND name='idx_leads_active_dedupe_key'
            """
        ).fetchone()
        if index is None:
            raise VerificationFailure("Workspace dedupe index is missing")
        normalized_index = " ".join(str(index["sql"] or "").lower().split())
        if (
            "on leads(organization_id, dedupe_key)" not in normalized_index
            or "where deleted_at is null" not in normalized_index
        ):
            raise VerificationFailure("Workspace dedupe index definition is invalid")

        membership_columns = set(_columns(db, "organization_memberships"))
        if "active" not in membership_columns:
            raise VerificationFailure("Membership revocation column is missing")

        owners_missing = db.execute(
            """
            SELECT u.id
            FROM users AS u
            WHERE u.role='owner' AND u.active=1
              AND EXISTS (
                SELECT 1
                FROM organizations AS required
                WHERE required.slug IN ('mark-agency', 'pendang')
                  AND NOT EXISTS (
                    SELECT 1
                    FROM organization_memberships AS m
                    WHERE m.user_id = u.id
                      AND m.organization_id = required.id
                      AND m.membership_role = 'workspace_admin'
                      AND m.active = 1
                  )
              )
            """
        ).fetchall()
        if owners_missing:
            raise VerificationFailure(
                "An active global Owner is missing an active workspace_admin membership"
            )

        foreign_key_errors = db.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise VerificationFailure("Foreign-key violations exist after rehearsal")

        quick_check = str(db.execute("PRAGMA quick_check").fetchone()[0])
        if quick_check.casefold() != "ok":
            raise VerificationFailure(f"PRAGMA quick_check failed: {quick_check}")

        journal_mode = str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    original = database.DB_PATH
    database.DB_PATH = path
    try:
        with database.get_db() as db:
            busy_timeout_ms = int(db.execute("PRAGMA busy_timeout").fetchone()[0])
    finally:
        database.DB_PATH = original

    if busy_timeout_ms <= 0:
        raise VerificationFailure("SQLite busy_timeout is not configured")

    return {
        "organizations": organizations,
        "lead_columns": sorted(lead_columns),
        "workspace_dedupe_index_sql": normalized_index,
        "membership_columns": sorted(membership_columns),
        "journal_mode": journal_mode,
        "busy_timeout_ms": busy_timeout_ms,
        "quick_check": quick_check,
        "foreign_key_errors": 0,
    }


def _compare_before_after(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_leads = before.get("lead_rows", [])
    after_leads = after.get("lead_rows", [])
    if before_leads != after_leads:
        raise VerificationFailure(
            "Rehearsal changed existing lead business fields, IDs, or quest links."
        )

    if before.get("activity_rows", []) != after.get("activity_rows", []):
        raise VerificationFailure(
            "Rehearsal changed existing lead activity IDs or lead links."
        )

    before_counts = before.get("table_counts", {})
    after_counts = after.get("table_counts", {})
    for protected_table in ("leads", "lead_activities", "tasks", "xp_ledger"):
        if protected_table in before_counts:
            if before_counts[protected_table] != after_counts.get(protected_table):
                raise VerificationFailure(
                    f"Rehearsal changed row count for protected table {protected_table}."
                )

    return {
        "lead_rows_preserved": len(before_leads),
        "activity_links_preserved": len(before.get("activity_rows", [])),
        "protected_table_counts": {
            table: after_counts.get(table)
            for table in ("leads", "lead_activities", "tasks", "xp_ledger")
            if table in before_counts
        },
    }


def _run_tests(*, full_suite: bool) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q"]
    if not full_suite:
        command.extend(ACCEPTANCE_TEST_FILES)
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        raise VerificationFailure(
            "Phase 6.6B acceptance pytest gate failed."
        )
    return {
        "status": "passed",
        "mode": "full" if full_suite else "acceptance",
        "command": " ".join(command),
    }


def run_rehearsal(
    source_db: Path,
    output_dir: Path,
    *,
    run_tests: bool = False,
    full_suite: bool = False,
) -> dict[str, Any]:
    source = source_db.expanduser().resolve()
    run_dir = output_dir.expanduser().resolve() / _stamp()
    backup_dir = run_dir / "backup"
    rehearsal_path = run_dir / "rehearsal" / "mark_os_phase_6_6b.sqlite3"
    report_path = run_dir / "phase_6_6b_verification.json"
    run_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "phase": "6.6B",
        "source_database": str(source),
        "run_directory": str(run_dir),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "manual_release_gates": {
            "railway_single_instance_confirmed": False,
            "production_volume_path_confirmed": False,
            "controlled_deploy_window_confirmed": False,
            "rey_onboarded_and_password_changed": False,
            "freddy_onboarded_and_password_changed": False,
            "three_real_pendang_leads_created": False,
            "one_pendang_lead_reviewed_by_rey": False,
            "pendang_next_action_due_date_verified": False,
            "production_health_verified": False,
        },
    }

    try:
        source_check = verify_sqlite_database(source)
        if not source_check.valid:
            raise VerificationFailure("Source database failed SQLite verification")
        report["source_verification"] = asdict(source_check)

        backup = create_sqlite_backup(
            source,
            backup_dir,
            backup_prefix="mark_os_phase_6_6b",
            keep_last=2,
        )
        report["online_backup"] = asdict(backup)

        manifest_check = verify_backup_manifest(
            backup.backup_path,
            backup.manifest_path,
        )
        if not manifest_check.valid:
            raise VerificationFailure("Backup manifest verification failed")
        report["manifest_verification"] = asdict(manifest_check)

        restore = restore_sqlite_backup(
            backup.backup_path,
            rehearsal_path,
            manifest_path=backup.manifest_path,
        )
        report["restore"] = asdict(restore)

        before = _snapshot_rehearsal_state(rehearsal_path)
        report["before_migration"] = before

        _run_migrations(rehearsal_path)

        after = _snapshot_rehearsal_state(rehearsal_path)
        report["after_migration"] = after
        report["preservation"] = _compare_before_after(before, after)
        report["schema_verification"] = _verify_phase_schema(rehearsal_path)
        report["health"] = _verify_health(rehearsal_path)

        final_check = verify_sqlite_database(rehearsal_path)
        if not final_check.valid:
            raise VerificationFailure(
                "Rehearsed database failed final SQLite verification"
            )
        report["final_verification"] = asdict(final_check)

        if run_tests:
            report["tests"] = _run_tests(full_suite=full_suite)
        else:
            report["tests"] = {"status": "skipped"}

        report["status"] = "passed"
        report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise

    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "report": report,
        "report_path": str(report_path),
        "rehearsal_database": str(rehearsal_path),
        "backup_path": backup.backup_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a verified SQLite online backup, restore it into an isolated "
            "rehearsal database, run the current Phase 6.6B migrations against "
            "that copy, and verify workspace/concurrency release invariants."
        )
    )
    parser.add_argument("--source-db", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".phase_6_6b_release"),
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run the Phase 6.6B acceptance test gate after the DB rehearsal.",
    )
    parser.add_argument(
        "--full-suite",
        action="store_true",
        help="With --run-tests, run the complete pytest suite instead of only the acceptance gate.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.full_suite and not args.run_tests:
        print("ERROR: --full-suite requires --run-tests", file=sys.stderr)
        return 2

    try:
        result = run_rehearsal(
            args.source_db,
            args.output_dir,
            run_tests=args.run_tests,
            full_suite=args.full_suite,
        )
    except Exception as error:
        print(f"Phase 6.6B rehearsal FAILED: {error}", file=sys.stderr)
        return 1

    print("Phase 6.6B database rehearsal PASSED")
    print(f"Backup: {result['backup_path']}")
    print(f"Rehearsal DB: {result['rehearsal_database']}")
    print(f"Report: {result['report_path']}")
    print("Manual Railway/onboarding gates remain intentionally unchecked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
