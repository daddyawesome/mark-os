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
            "Verify a MARK-OS SQLite backup and its checksum manifest."
        )
    )
    parser.add_argument("--backup", required=True)
    parser.add_argument(
        "--manifest",
        help="Defaults to <backup>.json.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    from app.services.database_backup import (
        verify_backup_manifest,
        verify_sqlite_database,
    )

    args = build_parser().parse_args(argv)
    backup = Path(args.backup).expanduser().resolve()
    try:
        database_result = verify_sqlite_database(backup)
        manifest_result = verify_backup_manifest(
            backup,
            args.manifest,
        )
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    healthy = database_result.valid and manifest_result.valid
    payload = {
        "healthy": healthy,
        "database": asdict(database_result),
        "manifest": asdict(manifest_result),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "MARK-OS backup verification "
            + ("PASSED" if healthy else "FAILED")
        )
        print(f"Backup: {backup}")
        print(f"Quick check: {database_result.quick_check}")
        print(
            "Foreign-key errors: "
            f"{database_result.foreign_key_errors}"
        )
        print(
            "Manifest checksum: "
            + ("matched" if manifest_result.valid else "mismatch")
        )
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
