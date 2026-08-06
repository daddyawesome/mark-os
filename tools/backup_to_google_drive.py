from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_REMOTE = "gdrive"
DEFAULT_FOLDER = "MARK-OS-Backups"
DEFAULT_KEEP_LAST = 14


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


def _run_rclone(
    arguments: list[str],
    *,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["rclone", *arguments]
    result = subprocess.run(
        command,
        check=False,
        capture_output=capture_output,
        text=True,
    )
    if result.returncode != 0:
        summary = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit code {result.returncode}"
        )
        raise RuntimeError(
            "rclone failed: "
            + " ".join(command[:3])
            + f": {summary[:1000]}"
        )
    return result


def _remote_path(
    remote: str,
    folder: str,
) -> str:
    remote_name = remote.strip().rstrip(":")
    folder_name = folder.strip().strip("/")
    if not remote_name:
        raise ValueError(
            "Google Drive remote name is required."
        )
    if not folder_name:
        raise ValueError(
            "Google Drive folder is required."
        )
    return f"{remote_name}:{folder_name}"


def _upload_and_verify(
    *,
    local_directory: Path,
    remote_directory: str,
    filenames: tuple[str, ...],
) -> None:
    filters: list[str] = []
    for filename in filenames:
        filters.extend(
            ["--include", f"/{filename}"]
        )
    filters.extend(["--exclude", "*"])

    _run_rclone(
        [
            "copy",
            str(local_directory),
            remote_directory,
            *filters,
            "--create-empty-src-dirs",
            "--retries",
            "3",
            "--low-level-retries",
            "5",
        ]
    )

    _run_rclone(
        [
            "check",
            str(local_directory),
            remote_directory,
            "--one-way",
            "--size-only",
            *filters,
        ]
    )


def _list_remote_files(
    remote_directory: str,
) -> list[dict[str, Any]]:
    result = _run_rclone(
        [
            "lsjson",
            remote_directory,
            "--files-only",
        ]
    )
    payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        raise RuntimeError(
            "Unexpected rclone lsjson response."
        )
    return [
        item
        for item in payload
        if isinstance(item, dict)
    ]


def _apply_remote_retention(
    *,
    remote_directory: str,
    prefix: str,
    keep_last: int,
) -> tuple[str, ...]:
    files = _list_remote_files(remote_directory)
    backup_names = sorted(
        (
            str(item.get("Name", ""))
            for item in files
            if str(item.get("Name", "")).startswith(
                f"{prefix}_"
            )
            and str(item.get("Name", "")).endswith(
                ".sqlite3"
            )
        ),
        reverse=True,
    )

    removed: list[str] = []
    for backup_name in backup_names[keep_last:]:
        manifest_name = backup_name + ".json"
        for filename in (
            backup_name,
            manifest_name,
        ):
            try:
                _run_rclone(
                    [
                        "deletefile",
                        f"{remote_directory}/{filename}",
                    ]
                )
                removed.append(filename)
            except RuntimeError as error:
                if "not found" not in str(error).casefold():
                    raise
    return tuple(removed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a verified temporary MARK-OS "
            "SQLite backup, upload it to Google Drive "
            "with rclone, verify the remote transfer, "
            "apply retention, and remove local "
            "temporary files."
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
        "--remote",
        help=(
            "rclone Google Drive remote name. "
            "Defaults to MARK_OS_GDRIVE_REMOTE or "
            f"{DEFAULT_REMOTE}."
        ),
    )
    parser.add_argument(
        "--folder",
        help=(
            "Google Drive backup folder. Defaults to "
            "MARK_OS_GDRIVE_FOLDER or "
            f"{DEFAULT_FOLDER}."
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
            "Number of newest Google Drive backups "
            "to retain. Defaults to "
            "MARK_OS_GDRIVE_KEEP_LAST or 14."
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

    if shutil.which("rclone") is None:
        print(
            "ERROR: rclone is not installed or is "
            "not available on PATH.",
            file=sys.stderr,
        )
        return 1

    source = Path(
        args.source or database.DB_PATH
    ).expanduser().resolve()
    remote = (
        args.remote
        or os.getenv(
            "MARK_OS_GDRIVE_REMOTE",
            DEFAULT_REMOTE,
        )
    )
    folder = (
        args.folder
        or os.getenv(
            "MARK_OS_GDRIVE_FOLDER",
            DEFAULT_FOLDER,
        )
    )
    prefix = (
        args.prefix
        or os.getenv(
            "MARK_OS_BACKUP_PREFIX",
            "mark_os",
        )
    )
    keep_last = (
        args.keep_last
        if args.keep_last is not None
        else int(
            os.getenv(
                "MARK_OS_GDRIVE_KEEP_LAST",
                str(DEFAULT_KEEP_LAST),
            )
        )
    )
    destination = _remote_path(
        remote,
        folder,
    )

    try:
        with tempfile.TemporaryDirectory(
            prefix="mark_os_gdrive_"
        ) as temporary_directory:
            temporary_path = Path(
                temporary_directory
            ).resolve()

            result = create_sqlite_backup(
                source_path=source,
                backup_directory=temporary_path,
                backup_prefix=prefix,
                keep_last=1,
            )

            backup_path = Path(
                result.backup_path
            )
            manifest_path = Path(
                result.manifest_path
            )
            filenames = (
                backup_path.name,
                manifest_path.name,
            )

            _upload_and_verify(
                local_directory=temporary_path,
                remote_directory=destination,
                filenames=filenames,
            )

            removed = _apply_remote_retention(
                remote_directory=destination,
                prefix=prefix,
                keep_last=keep_last,
            )

            payload = {
                **asdict(result),
                "google_drive_remote": destination,
                "uploaded_files": list(filenames),
                "remote_retention_keep_last": (
                    keep_last
                ),
                "remote_retention_removed": list(
                    removed
                ),
                "temporary_files_removed": True,
            }

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
                "MARK-OS Google Drive backup "
                "completed."
            )
            print(f"Source: {source}")
            print(
                "Google Drive destination: "
                f"{destination}"
            )
            print(
                "Uploaded backup: "
                f"{filenames[0]}"
            )
            print(
                "Uploaded manifest: "
                f"{filenames[1]}"
            )
            print(
                "Quick check: "
                f"{result.quick_check}"
            )
            print(
                "Foreign-key errors: "
                f"{result.foreign_key_errors}"
            )
            print(f"SHA-256: {result.sha256}")
            print(
                "Remote verification: passed"
            )
            print(
                "Remote retention: newest "
                f"{keep_last}"
            )
            print(
                "Removed from Google Drive: "
                f"{len(removed)}"
            )
            print(
                "Temporary Railway files removed: "
                "yes"
            )
        return 0

    except Exception as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
