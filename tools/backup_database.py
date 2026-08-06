from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence


DEFAULT_KEEP_LAST = 14



PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "must be a whole number"
        ) from error
    if parsed < 1:
        raise argparse.ArgumentTypeError(
            "must be at least 1"
        )
    return parsed


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create, verify, checksum, and retain a "
            "timestamped MARK-OS SQLite backup."
        )
    )
    parser.add_argument(
        "--source",
        help=(
            "SQLite source path. Defaults to "
            "app.database.DB_PATH."
        ),
    )
    parser.add_argument(
        "--destination",
        help=(
            "Backup directory. Defaults to "
            "MARK_OS_BACKUP_DIR or <database>/backups."
        ),
    )
    parser.add_argument(
        "--prefix",
        help=(
            "Backup filename prefix. Defaults to "
            "MARK_OS_BACKUP_PREFIX or mark_os."
        ),
    )
    parser.add_argument(
        "--keep-last",
        type=_positive_integer,
        help=(
            "Number of newest backups to retain. Defaults "
            "to MARK_OS_BACKUP_KEEP_LAST or 14."
        ),
    )
    parser.add_argument(
        "--event-log",
        help=(
            "Optional JSONL event log path. Defaults to "
            "backup_events.jsonl in the backup directory."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv()
    from app import database
    from app.services.database_backup import (
        create_sqlite_backup,
    )

    args = build_parser().parse_args(argv)
    source = Path(
        args.source or database.DB_PATH
    ).expanduser().resolve()
    destination = Path(
        args.destination
        or os.getenv("MARK_OS_BACKUP_DIR", "")
        or source.parent / "backups"
    ).expanduser().resolve()
    prefix = (
        args.prefix
        or os.getenv("MARK_OS_BACKUP_PREFIX", "mark_os")
    )
    raw_keep_last = (
        args.keep_last
        if args.keep_last is not None
        else os.getenv(
            "MARK_OS_BACKUP_KEEP_LAST",
            str(DEFAULT_KEEP_LAST),
        )
    )
    keep_last = int(raw_keep_last)

    volume_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if volume_mount:
        mount_path = Path(volume_mount).expanduser().resolve()
        if not _is_within(source, mount_path):
            print(
                "ERROR: Railway database is not inside the "
                f"persistent volume: {mount_path}",
                file=sys.stderr,
            )
            return 1
        if not _is_within(destination, mount_path):
            print(
                "ERROR: Railway backup directory is not inside "
                f"the persistent volume: {mount_path}",
                file=sys.stderr,
            )
            return 1

    try:
        result = create_sqlite_backup(
            source_path=source,
            backup_directory=destination,
            backup_prefix=prefix,
            keep_last=keep_last,
            event_log_path=args.event_log,
        )
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print("MARK-OS backup completed.")
        print(f"Source: {result.source_path}")
        print(f"Backup: {result.backup_path}")
        print(f"Manifest: {result.manifest_path}")
        print(f"Event log: {result.event_log_path}")
        print(f"Size: {result.size_bytes} bytes")
        print(f"SHA-256: {result.sha256}")
        print(f"Quick check: {result.quick_check}")
        print(
            "Foreign-key errors: "
            f"{result.foreign_key_errors}"
        )
        print(f"Retention: newest {keep_last}")
        print(
            "Removed by retention: "
            f"{len(result.retention_removed)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
