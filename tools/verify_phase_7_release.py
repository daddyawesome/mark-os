from __future__ import annotations

import argparse
import hashlib
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
from app.services.operations_monitoring import build_health_response


class VerificationFailure(RuntimeError):
    pass


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(value: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{value}^{{commit}}"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise VerificationFailure(f"Git rollback target is not a commit: {value}")
    return result.stdout.strip()


def _snapshot_existing_fields(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = [
            str(row["name"])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]
        snapshot: dict[str, Any] = {}
        for table in tables:
            columns = [
                str(row["name"])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            rows = [
                [row[column] for column in columns]
                for row in connection.execute(
                    f'SELECT * FROM "{table}" ORDER BY rowid'
                )
            ]
            snapshot[table] = {"columns": columns, "rows": rows}
        return snapshot
    finally:
        connection.close()


def _assert_preserved(before: dict[str, Any], after_path: Path) -> dict[str, int]:
    after = _snapshot_existing_fields(after_path)
    counts: dict[str, int] = {}
    for table, original in before.items():
        if table not in after:
            raise VerificationFailure(f"Migration removed existing table: {table}")
        columns = original["columns"]
        current_columns = after[table]["columns"]
        if any(column not in current_columns for column in columns):
            raise VerificationFailure(f"Migration removed a column from {table}")
        indexes = [current_columns.index(column) for column in columns]
        projected = [
            [row[index] for index in indexes] for row in after[table]["rows"]
        ]
        if projected != original["rows"]:
            raise VerificationFailure(f"Migration changed existing rows in {table}")
        counts[table] = len(projected)
    return counts


def _migrate(path: Path) -> None:
    original = database.DB_PATH
    database.DB_PATH = path
    try:
        database.init_db()
    finally:
        database.DB_PATH = original


def _verify_phase_7_schema(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required = {"auth_sessions", "login_attempts", "security_audit_events"}
        missing = required - tables
        if missing:
            raise VerificationFailure(
                "Missing Phase 7 tables: " + ", ".join(sorted(missing))
            )
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(checkins)")
        }
        if "request_key" not in columns:
            raise VerificationFailure("checkins.request_key is missing")
        index = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'idx_checkins_user_request_key'"
        ).fetchone()
        if index is None or "WHERE request_key IS NOT NULL" not in str(index["sql"]):
            raise VerificationFailure("Check-in retry idempotency index is missing")
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if quick_check.casefold() != "ok" or foreign_keys:
            raise VerificationFailure("Staging database integrity verification failed")
        return {
            "required_tables": sorted(required),
            "checkin_request_key": True,
            "quick_check": quick_check,
            "foreign_key_errors": len(foreign_keys),
        }
    finally:
        connection.close()


def run_rehearsal(
    source_db: Path,
    output_dir: Path,
    *,
    release_commit: str,
    last_known_good_commit: str,
    drill_label: str = "manual",
) -> dict[str, Any]:
    source = source_db.expanduser().resolve()
    output = output_dir.expanduser().resolve()
    if PROJECT_ROOT == output or PROJECT_ROOT in output.parents:
        raise VerificationFailure("Phase 7 evidence must be stored outside Git.")
    run_dir = output / _stamp()
    backup_dir = run_dir / "rollback-backup"
    staging_path = run_dir / "staging" / "mark_os_staging.sqlite3"
    report_path = run_dir / "phase_7_release_evidence.json"
    run_dir.mkdir(parents=True, exist_ok=False)

    report: dict[str, Any] = {
        "phase": "7.6",
        "status": "running",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "drill_label": drill_label,
        "source_database": str(source),
        "release_commit": _git_commit(release_commit),
        "last_known_good_commit": _git_commit(last_known_good_commit),
        "manual_release_gates": {
            "railway_single_instance_confirmed": False,
            "production_volume_path_confirmed": False,
            "production_backup_downloaded_and_verified": False,
            "production_health_verified_after_deploy": False,
        },
    }

    try:
        source_hash = _sha256(source)
        source_check = verify_sqlite_database(source)
        if not source_check.valid:
            raise VerificationFailure("Source database failed verification")
        report["source_verification"] = asdict(source_check)

        backup = create_sqlite_backup(
            source, backup_dir, backup_prefix="mark_os_phase_7_rollback", keep_last=2
        )
        report["rollback_backup"] = asdict(backup)
        manifest = verify_backup_manifest(backup.backup_path, backup.manifest_path)
        if not manifest.valid:
            raise VerificationFailure("Rollback backup manifest failed verification")
        report["rollback_manifest"] = asdict(manifest)

        restore = restore_sqlite_backup(
            backup.backup_path, staging_path, manifest_path=backup.manifest_path
        )
        report["staging_restore"] = asdict(restore)
        before = _snapshot_existing_fields(staging_path)
        _migrate(staging_path)
        report["preserved_rows"] = _assert_preserved(before, staging_path)
        after_first = _snapshot_existing_fields(staging_path)
        _migrate(staging_path)
        report["idempotent_rows"] = _assert_preserved(after_first, staging_path)
        report["schema"] = _verify_phase_7_schema(staging_path)

        health = build_health_response(staging_path)
        report["health"] = {
            "status_code": health.status_code,
            "payload": json.loads(health.body),
        }
        if health.status_code != 200:
            raise VerificationFailure("Staging health check failed")
        final_check = verify_sqlite_database(staging_path)
        if not final_check.valid:
            raise VerificationFailure("Final staging database verification failed")
        report["final_verification"] = asdict(final_check)
        if _sha256(source) != source_hash:
            raise VerificationFailure("Source database changed during rehearsal")
        report["source_preserved"] = True
        report["rollback_procedure"] = {
            "code": "Redeploy last_known_good_commit; do not restore a healthy database.",
            "database": (
                "Stop writes, back up the failed state, verify rollback_backup, "
                "restore to a new filename, smoke-test it, then switch MARK_OS_DB_PATH."
            ),
        }
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)
        raise
    finally:
        report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    return {
        "report": report,
        "report_path": str(report_path),
        "staging_database": str(staging_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rehearse Phase 7 against an isolated verified SQLite copy."
    )
    parser.add_argument("--source-db", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "mark-os-release-evidence" / "phase-7",
    )
    parser.add_argument("--release-commit", required=True)
    parser.add_argument("--last-known-good-commit", required=True)
    parser.add_argument("--drill-label", default="manual")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_rehearsal(
            args.source_db,
            args.output_dir,
            release_commit=args.release_commit,
            last_known_good_commit=args.last_known_good_commit,
            drill_label=args.drill_label,
        )
    except Exception as exc:
        print(f"Phase 7 staging rehearsal FAILED: {exc}", file=sys.stderr)
        return 1
    print("Phase 7 staging rehearsal PASSED")
    print(f"Staging database: {result['staging_database']}")
    print(f"Evidence: {result['report_path']}")
    print("Manual Railway gates remain unchecked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
