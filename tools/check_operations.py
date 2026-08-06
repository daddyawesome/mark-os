from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _positive_integer(value: str) -> int:
    parsed = int(value)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check MARK-OS /health and verified backup freshness, "
            "then send one Owner webhook alert on failure."
        )
    )
    parser.add_argument(
        "--health-url",
        help=(
            "Public /health URL. Defaults to "
            "MARK_OS_HEALTH_URL."
        ),
    )
    parser.add_argument(
        "--backup-directory",
        help=(
            "Backup directory. Defaults to MARK_OS_BACKUP_DIR "
            "or <database>/backups."
        ),
    )
    parser.add_argument(
        "--prefix",
        help=(
            "Backup prefix. Defaults to "
            "MARK_OS_BACKUP_PREFIX or mark_os."
        ),
    )
    parser.add_argument(
        "--max-age-hours",
        type=_positive_integer,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=_positive_integer,
    )
    parser.add_argument(
        "--no-alert",
        action="store_true",
        help="Run checks without sending the Owner webhook.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable result.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
) -> int:
    _load_dotenv()
    from app import database
    from app.services.database_backup import (
        DEFAULT_MAX_AGE_HOURS,
    )
    from app.services.operations_monitoring import (
        DEFAULT_HEALTH_TIMEOUT_SECONDS,
        operations_check_as_dict,
        run_operations_check,
    )

    args = build_parser().parse_args(argv)
    health_url = (
        args.health_url
        or os.getenv("MARK_OS_HEALTH_URL", "")
    ).strip()
    if not health_url:
        print(
            "ERROR: Set MARK_OS_HEALTH_URL or pass --health-url.",
            file=sys.stderr,
        )
        return 2

    source = Path(
        database.DB_PATH
    ).expanduser().resolve()
    backup_directory = Path(
        args.backup_directory
        or os.getenv("MARK_OS_BACKUP_DIR", "")
        or source.parent / "backups"
    ).expanduser().resolve()
    prefix = (
        args.prefix
        or os.getenv(
            "MARK_OS_BACKUP_PREFIX",
            "mark_os",
        )
    )
    max_age_hours = (
        args.max_age_hours
        or int(
            os.getenv(
                "MARK_OS_BACKUP_MAX_AGE_HOURS",
                str(DEFAULT_MAX_AGE_HOURS),
            )
        )
    )
    timeout_seconds = (
        args.timeout_seconds
        or int(
            os.getenv(
                "MARK_OS_HEALTH_TIMEOUT_SECONDS",
                str(DEFAULT_HEALTH_TIMEOUT_SECONDS),
            )
        )
    )

    result = run_operations_check(
        health_url=health_url,
        backup_directory=backup_directory,
        backup_prefix=prefix,
        max_age_hours=max_age_hours,
        timeout_seconds=timeout_seconds,
        send_alert=not args.no_alert,
    )
    payload = operations_check_as_dict(result)

    if args.json:
        print(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(
            "MARK-OS operations status: "
            + (
                "HEALTHY"
                if result.healthy
                else "UNHEALTHY"
            )
        )
        print(
            "Application health: "
            f"{result.uptime.status}"
        )
        print(
            "Backup health: "
            f"{result.backup.status}"
        )
        print(
            "Backup age hours: "
            f"{result.backup.age_hours}"
        )
        print(
            "Owner alert: "
            f"{result.alert.status}"
        )

    return 0 if result.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
