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
    check_backup_status,
    create_sqlite_backup,
    restore_sqlite_backup,
    verify_backup_manifest,
    verify_sqlite_database,
)


class VerificationFailure(RuntimeError):
    pass


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )


def _table_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(
        f"{path.as_uri()}?mode=ro",
        uri=True,
    )
    try:
        table_rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        return {
            str(row[0]): int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{row[0]}"'
                ).fetchone()[0]
            )
            for row in table_rows
        }
    finally:
        connection.close()


def _run_restored_startup(restored_path: Path) -> dict[str, Any]:
    original_path = database.DB_PATH
    database.DB_PATH = restored_path
    try:
        database.init_db()
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            response = client.get("/health")
        if response.status_code != 200:
            raise VerificationFailure(
                "Restored MARK-OS health check returned "
                f"HTTP {response.status_code}."
            )
        return {
            "status": "passed",
            "http_status": response.status_code,
            "response": response.json(),
        }
    finally:
        database.DB_PATH = original_path


def _run_tests() -> dict[str, str]:
    command = [sys.executable, "-m", "pytest", "-q"]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise VerificationFailure(
            "The complete pytest suite failed."
        )
    return {
        "status": "passed",
        "command": " ".join(command),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Produce a verified backup, restore it into a new "
            "SQLite file, start MARK-OS against the restored copy, "
            "and write Phase 6.2 release evidence."
        )
    )
    parser.add_argument(
        "--source-db",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".phase_6_2_release"),
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source_db.expanduser().resolve()
    run_dir = args.output_dir.expanduser().resolve() / _stamp()
    backup_dir = run_dir / "backups"
    restored_path = run_dir / "restored" / "mark_os_restored.sqlite3"
    report_path = run_dir / "phase_6_2_verification.json"
    run_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "phase": "6.2",
        "source_database": str(source),
        "run_directory": str(run_dir),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }

    try:
        source_check = verify_sqlite_database(source)
        if not source_check.valid:
            raise VerificationFailure(
                "Source database failed SQLite verification."
            )
        report["source_verification"] = asdict(source_check)

        backup = create_sqlite_backup(
            source,
            backup_dir,
            backup_prefix="mark_os_release",
            keep_last=2,
        )
        report["backup"] = asdict(backup)

        manifest_check = verify_backup_manifest(
            backup.backup_path,
            backup.manifest_path,
        )
        if not manifest_check.valid:
            raise VerificationFailure(
                "Backup manifest verification failed."
            )
        report["manifest_verification"] = asdict(
            manifest_check
        )

        status = check_backup_status(
            backup_dir,
            backup_prefix="mark_os_release",
            max_age_hours=1,
        )
        if not status.healthy:
            raise VerificationFailure(
                f"Fresh backup status failed: {status.reason}"
            )
        report["backup_status"] = asdict(status)

        restore = restore_sqlite_backup(
            backup.backup_path,
            restored_path,
            manifest_path=backup.manifest_path,
        )
        report["restore"] = asdict(restore)

        backup_counts = _table_counts(Path(backup.backup_path))
        restored_counts = _table_counts(restored_path)
        if backup_counts != restored_counts:
            raise VerificationFailure(
                "Backup and restored table counts do not match."
            )
        report["table_counts"] = restored_counts

        report["restored_startup"] = _run_restored_startup(
            restored_path
        )
        final_check = verify_sqlite_database(restored_path)
        if not final_check.valid:
            raise VerificationFailure(
                "Restored database failed final verification."
            )
        report["restored_final_verification"] = asdict(
            final_check
        )

        report["tests"] = (
            _run_tests()
            if args.run_tests
            else {"status": "skipped"}
        )
        report["status"] = "passed"
        report["completed_at_utc"] = datetime.now(
            timezone.utc
        ).isoformat()
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        report["completed_at_utc"] = datetime.now(
            timezone.utc
        ).isoformat()
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"FAILED: {error}", file=sys.stderr)
        print(f"Report: {report_path}", file=sys.stderr)
        return 1

    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("Phase 6.2 verification PASSED")
    print(f"Backup: {backup.backup_path}")
    print(f"Restored: {restored_path}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
