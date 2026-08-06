from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence



PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Restore a verified MARK-OS backup into a new SQLite file. "
            "The configured live database is never overwritten."
        )
    )
    parser.add_argument("--backup", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--manifest")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing a non-live destination file.",
    )
    parser.add_argument(
        "--without-manifest",
        action="store_true",
        help=(
            "Emergency-only mode when the manifest is unavailable. "
            "SQLite integrity checks still run."
        ),
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    from app import database
    from app.services.database_backup import restore_sqlite_backup

    args = build_parser().parse_args(argv)
    backup = Path(args.backup).expanduser().resolve()
    destination = Path(args.destination).expanduser().resolve()
    active_database = Path(database.DB_PATH).expanduser().resolve()

    if destination == active_database:
        print(
            "ERROR: refusing to overwrite the configured live database. "
            "Restore to a new file, verify it, then change "
            "MARK_OS_DB_PATH during a controlled Railway deployment.",
            file=sys.stderr,
        )
        return 1

    try:
        result = restore_sqlite_backup(
            backup_path=backup,
            restored_path=destination,
            manifest_path=args.manifest,
            overwrite=args.overwrite,
            require_manifest=not args.without_manifest,
        )
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print("MARK-OS restore completed.")
        print(f"Backup: {result.backup_path}")
        print(f"Manifest: {result.manifest_path}")
        print(f"Restored: {result.restored_path}")
        print(f"Size: {result.size_bytes} bytes")
        print(f"SHA-256: {result.sha256}")
        print(f"Quick check: {result.quick_check}")
        print(
            "Foreign-key errors: "
            f"{result.foreign_key_errors}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
