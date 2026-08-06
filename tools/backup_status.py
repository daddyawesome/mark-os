from __future__ import annotations

import sys
import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Sequence



PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when the newest MARK-OS backup is missing, stale, "
            "corrupt, or does not match its manifest."
        )
    )
    parser.add_argument("--directory")
    parser.add_argument("--prefix")
    parser.add_argument(
        "--max-age-hours",
        type=_positive_integer,
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    from app import database
    from app.services.database_backup import (
        DEFAULT_MAX_AGE_HOURS,
        check_backup_status,
    )

    args = build_parser().parse_args(argv)
    source = Path(database.DB_PATH).expanduser().resolve()
    directory = Path(
        args.directory
        or os.getenv("MARK_OS_BACKUP_DIR", "")
        or source.parent / "backups"
    ).expanduser().resolve()
    prefix = (
        args.prefix
        or os.getenv("MARK_OS_BACKUP_PREFIX", "mark_os")
    )
    max_age = (
        args.max_age_hours
        or int(
            os.getenv(
                "MARK_OS_BACKUP_MAX_AGE_HOURS",
                str(DEFAULT_MAX_AGE_HOURS),
            )
        )
    )

    result = check_backup_status(
        directory,
        backup_prefix=prefix,
        max_age_hours=max_age,
    )
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print(
            "MARK-OS backup status: "
            + ("HEALTHY" if result.healthy else "UNHEALTHY")
        )
        print(f"Directory: {result.backup_directory}")
        print(f"Latest: {result.latest_backup_path}")
        print(f"Age hours: {result.age_hours}")
        print(f"Reason: {result.reason}")
    return 0 if result.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())