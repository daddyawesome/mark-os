from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final


MANIFEST_VERSION: Final[int] = 1
DEFAULT_KEEP_LAST: Final[int] = 14
DEFAULT_MAX_AGE_HOURS: Final[int] = 26
BACKUP_SUFFIX: Final[str] = ".sqlite3"
EVENT_LOG_NAME: Final[str] = "backup_events.jsonl"


@dataclass(frozen=True)
class VerificationResult:
    database_path: str
    quick_check: str
    foreign_key_errors: int
    size_bytes: int
    sha256: str
    valid: bool


@dataclass(frozen=True)
class ManifestVerificationResult:
    backup_path: str
    manifest_path: str
    expected_sha256: str
    actual_sha256: str
    expected_size_bytes: int
    actual_size_bytes: int
    valid: bool


@dataclass(frozen=True)
class BackupResult:
    source_path: str
    backup_path: str
    manifest_path: str
    event_log_path: str
    created_at_utc: str
    size_bytes: int
    sha256: str
    quick_check: str
    foreign_key_errors: int
    retention_removed: tuple[str, ...]


@dataclass(frozen=True)
class RestoreResult:
    backup_path: str
    manifest_path: str
    restored_path: str
    restored_at_utc: str
    size_bytes: int
    sha256: str
    quick_check: str
    foreign_key_errors: int


@dataclass(frozen=True)
class BackupStatus:
    backup_directory: str
    latest_backup_path: str | None
    latest_manifest_path: str | None
    age_hours: float | None
    max_age_hours: int
    healthy: bool
    reason: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_timestamp() -> str:
    return _utc_now().strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(
            lambda: file_handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)
    return digest.hexdigest()


def _read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{path.as_uri()}?mode=ro",
        uri=True,
        timeout=30,
    )
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _write_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=30)
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _safe_prefix(value: str) -> str:
    safe = "".join(
        character
        for character in value
        if character.isalnum() or character in {"-", "_"}
    ).strip("_-")
    if not safe:
        raise ValueError(
            "backup_prefix must contain letters or numbers."
        )
    return safe


def manifest_path_for_backup(backup_path: str | Path) -> Path:
    backup = Path(backup_path).expanduser().resolve()
    return backup.with_suffix(backup.suffix + ".json")


def event_log_path_for_directory(
    backup_directory: str | Path,
) -> Path:
    return (
        Path(backup_directory).expanduser().resolve()
        / EVENT_LOG_NAME
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    with temporary.open("rb") as file_handle:
        os.fsync(file_handle.fileno())
    os.replace(temporary, path)


def _append_event(
    event_log_path: Path,
    payload: dict[str, Any],
) -> None:
    event_log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, sort_keys=True) + "\n"
    with event_log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _record_failure(
    *,
    event_log_path: Path,
    source_path: Path,
    backup_directory: Path,
    error: Exception,
) -> None:
    try:
        _append_event(
            event_log_path,
            {
                "event": "backup",
                "status": "failed",
                "created_at_utc": _utc_now().isoformat(),
                "source_path": str(source_path),
                "backup_directory": str(backup_directory),
                "error_type": type(error).__name__,
                "error_summary": str(error)[:500],
            },
        )
    except OSError:
        # Preserve the original backup error even when logging also fails.
        pass


def verify_sqlite_database(
    database_path: str | Path,
) -> VerificationResult:
    path = Path(database_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"Database does not exist: {path}"
        )
    if not path.is_file():
        raise ValueError(
            f"Database path is not a file: {path}"
        )

    with _read_only_connection(path) as connection:
        quick_check_row = connection.execute(
            "PRAGMA quick_check"
        ).fetchone()
        quick_check = (
            str(quick_check_row[0])
            if quick_check_row
            else "no result"
        )
        foreign_key_errors = len(
            connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
        )

    size_bytes = path.stat().st_size
    sha256 = _sha256(path)
    valid = (
        quick_check.casefold() == "ok"
        and foreign_key_errors == 0
    )
    return VerificationResult(
        database_path=str(path),
        quick_check=quick_check,
        foreign_key_errors=foreign_key_errors,
        size_bytes=size_bytes,
        sha256=sha256,
        valid=valid,
    )


def load_backup_manifest(
    manifest_path: str | Path,
) -> dict[str, Any]:
    path = Path(manifest_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"Backup manifest does not exist: {path}"
        )
    if not path.is_file():
        raise ValueError(
            f"Backup manifest path is not a file: {path}"
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Backup manifest must contain an object.")
    if payload.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError(
            "Unsupported backup manifest version: "
            f"{payload.get('manifest_version')!r}"
        )
    return payload


def verify_backup_manifest(
    backup_path: str | Path,
    manifest_path: str | Path | None = None,
) -> ManifestVerificationResult:
    backup = Path(backup_path).expanduser().resolve()
    manifest = (
        Path(manifest_path).expanduser().resolve()
        if manifest_path is not None
        else manifest_path_for_backup(backup)
    )

    if not backup.exists():
        raise FileNotFoundError(
            f"Backup database does not exist: {backup}"
        )
    if not backup.is_file():
        raise ValueError(
            f"Backup path is not a file: {backup}"
        )

    payload = load_backup_manifest(manifest)
    expected_sha256 = str(payload.get("sha256", ""))
    expected_size = int(payload.get("size_bytes", -1))
    actual_sha256 = _sha256(backup)
    actual_size = backup.stat().st_size
    valid = (
        expected_sha256 == actual_sha256
        and expected_size == actual_size
        and payload.get("backup_filename") == backup.name
    )

    return ManifestVerificationResult(
        backup_path=str(backup),
        manifest_path=str(manifest),
        expected_sha256=expected_sha256,
        actual_sha256=actual_sha256,
        expected_size_bytes=expected_size,
        actual_size_bytes=actual_size,
        valid=valid,
    )


def _remove_old_backups(
    *,
    backup_directory: Path,
    backup_prefix: str,
    keep_last: int,
    protected_paths: set[Path],
) -> tuple[str, ...]:
    if keep_last < 1:
        raise ValueError("keep_last must be at least 1.")

    candidates = sorted(
        (
            path
            for path in backup_directory.glob(
                f"{backup_prefix}_*{BACKUP_SUFFIX}"
            )
            if path.is_file()
            and path.resolve() not in protected_paths
        ),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )

    removed: list[str] = []
    for old_backup in candidates[keep_last:]:
        old_manifest = manifest_path_for_backup(old_backup)
        old_backup.unlink(missing_ok=True)
        old_manifest.unlink(missing_ok=True)
        removed.append(str(old_backup))
    return tuple(removed)


def create_sqlite_backup(
    source_path: str | Path,
    backup_directory: str | Path,
    *,
    backup_prefix: str = "mark_os",
    keep_last: int = DEFAULT_KEEP_LAST,
    event_log_path: str | Path | None = None,
) -> BackupResult:
    source = Path(source_path).expanduser().resolve()
    destination_directory = (
        Path(backup_directory).expanduser().resolve()
    )
    safe_prefix = _safe_prefix(backup_prefix)
    if keep_last < 1:
        raise ValueError("keep_last must be at least 1.")

    destination_directory.mkdir(parents=True, exist_ok=True)
    resolved_event_log = (
        Path(event_log_path).expanduser().resolve()
        if event_log_path is not None
        else event_log_path_for_directory(destination_directory)
    )

    timestamp = _utc_timestamp()
    final_path = (
        destination_directory
        / f"{safe_prefix}_{timestamp}{BACKUP_SUFFIX}"
    )
    temporary_path = final_path.with_suffix(
        final_path.suffix + ".tmp"
    )
    manifest_path = manifest_path_for_backup(final_path)
    temporary_path.unlink(missing_ok=True)

    try:
        if not source.exists():
            raise FileNotFoundError(
                f"Source database does not exist: {source}"
            )
        if not source.is_file():
            raise ValueError(
                "Source database path is not a file: "
                f"{source}"
            )
        if final_path.resolve() == source:
            raise ValueError(
                "Backup destination cannot be the live database."
            )

        source_connection = _read_only_connection(source)
        destination_connection = _write_connection(temporary_path)
        try:
            source_connection.backup(
                destination_connection,
                pages=256,
                sleep=0.05,
            )
            destination_connection.commit()
        finally:
            destination_connection.close()
            source_connection.close()

        verification = verify_sqlite_database(temporary_path)
        if not verification.valid:
            raise RuntimeError(
                "Backup verification failed: "
                f"quick_check={verification.quick_check!r}, "
                "foreign_key_errors="
                f"{verification.foreign_key_errors}"
            )

        os.replace(temporary_path, final_path)
        final_verification = verify_sqlite_database(final_path)
        created_at = _utc_now().isoformat()

        manifest_payload = {
            "manifest_version": MANIFEST_VERSION,
            "kind": "mark_os_sqlite_backup",
            "created_at_utc": created_at,
            "source_path": str(source),
            "source_filename": source.name,
            "backup_filename": final_path.name,
            "size_bytes": final_verification.size_bytes,
            "sha256": final_verification.sha256,
            "quick_check": final_verification.quick_check,
            "foreign_key_errors": (
                final_verification.foreign_key_errors
            ),
            "valid": final_verification.valid,
        }
        _atomic_write_text(
            manifest_path,
            json.dumps(
                manifest_payload,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

        retention_removed = _remove_old_backups(
            backup_directory=destination_directory,
            backup_prefix=safe_prefix,
            keep_last=keep_last,
            protected_paths={source},
        )

        _append_event(
            resolved_event_log,
            {
                "event": "backup",
                "status": "succeeded",
                "created_at_utc": created_at,
                "source_path": str(source),
                "backup_path": str(final_path),
                "manifest_path": str(manifest_path),
                "size_bytes": final_verification.size_bytes,
                "sha256": final_verification.sha256,
                "quick_check": final_verification.quick_check,
                "foreign_key_errors": (
                    final_verification.foreign_key_errors
                ),
                "retention_removed": list(retention_removed),
            },
        )

        return BackupResult(
            source_path=str(source),
            backup_path=str(final_path),
            manifest_path=str(manifest_path),
            event_log_path=str(resolved_event_log),
            created_at_utc=created_at,
            size_bytes=final_verification.size_bytes,
            sha256=final_verification.sha256,
            quick_check=final_verification.quick_check,
            foreign_key_errors=(
                final_verification.foreign_key_errors
            ),
            retention_removed=retention_removed,
        )
    except Exception as error:
        temporary_path.unlink(missing_ok=True)
        _record_failure(
            event_log_path=resolved_event_log,
            source_path=source,
            backup_directory=destination_directory,
            error=error,
        )
        raise


def restore_sqlite_backup(
    backup_path: str | Path,
    restored_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    overwrite: bool = False,
    require_manifest: bool = True,
) -> RestoreResult:
    backup = Path(backup_path).expanduser().resolve()
    destination = Path(restored_path).expanduser().resolve()
    manifest = (
        Path(manifest_path).expanduser().resolve()
        if manifest_path is not None
        else manifest_path_for_backup(backup)
    )

    if backup == destination:
        raise ValueError(
            "Restore destination must be a new database file."
        )
    if not backup.exists():
        raise FileNotFoundError(
            f"Backup database does not exist: {backup}"
        )
    if not backup.is_file():
        raise ValueError(
            f"Backup path is not a file: {backup}"
        )
    if destination.exists() and not overwrite:
        raise FileExistsError(
            "Restore destination already exists. "
            "Pass overwrite=True only after confirming the path."
        )

    backup_verification = verify_sqlite_database(backup)
    if not backup_verification.valid:
        raise RuntimeError(
            "Backup database is not valid: "
            f"quick_check={backup_verification.quick_check!r}, "
            "foreign_key_errors="
            f"{backup_verification.foreign_key_errors}"
        )

    if require_manifest:
        manifest_verification = verify_backup_manifest(
            backup,
            manifest,
        )
        if not manifest_verification.valid:
            raise RuntimeError(
                "Backup manifest checksum or size does not match "
                "the backup file."
            )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(
        destination.suffix + ".restore.tmp"
    )
    temporary_path.unlink(missing_ok=True)

    try:
        source_connection = _read_only_connection(backup)
        destination_connection = _write_connection(temporary_path)
        try:
            source_connection.backup(
                destination_connection,
                pages=256,
                sleep=0.05,
            )
            destination_connection.commit()
        finally:
            destination_connection.close()
            source_connection.close()

        verification = verify_sqlite_database(temporary_path)
        if not verification.valid:
            raise RuntimeError(
                "Restored database verification failed: "
                f"quick_check={verification.quick_check!r}, "
                "foreign_key_errors="
                f"{verification.foreign_key_errors}"
            )

        if overwrite:
            destination.unlink(missing_ok=True)
        os.replace(temporary_path, destination)
        final_verification = verify_sqlite_database(destination)

        return RestoreResult(
            backup_path=str(backup),
            manifest_path=(
                str(manifest) if require_manifest else ""
            ),
            restored_path=str(destination),
            restored_at_utc=_utc_now().isoformat(),
            size_bytes=final_verification.size_bytes,
            sha256=final_verification.sha256,
            quick_check=final_verification.quick_check,
            foreign_key_errors=(
                final_verification.foreign_key_errors
            ),
        )
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def check_backup_status(
    backup_directory: str | Path,
    *,
    backup_prefix: str = "mark_os",
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> BackupStatus:
    directory = Path(backup_directory).expanduser().resolve()
    safe_prefix = _safe_prefix(backup_prefix)
    if max_age_hours < 1:
        raise ValueError("max_age_hours must be at least 1.")

    if not directory.exists():
        return BackupStatus(
            backup_directory=str(directory),
            latest_backup_path=None,
            latest_manifest_path=None,
            age_hours=None,
            max_age_hours=max_age_hours,
            healthy=False,
            reason="Backup directory does not exist.",
        )

    backups = sorted(
        (
            path
            for path in directory.glob(
                f"{safe_prefix}_*{BACKUP_SUFFIX}"
            )
            if path.is_file()
        ),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )
    if not backups:
        return BackupStatus(
            backup_directory=str(directory),
            latest_backup_path=None,
            latest_manifest_path=None,
            age_hours=None,
            max_age_hours=max_age_hours,
            healthy=False,
            reason="No backup files were found.",
        )

    latest = backups[0]
    manifest = manifest_path_for_backup(latest)
    age_hours = (
        _utc_now().timestamp() - latest.stat().st_mtime
    ) / 3600

    try:
        database_check = verify_sqlite_database(latest)
        manifest_check = verify_backup_manifest(latest, manifest)
    except Exception as error:
        return BackupStatus(
            backup_directory=str(directory),
            latest_backup_path=str(latest),
            latest_manifest_path=str(manifest),
            age_hours=age_hours,
            max_age_hours=max_age_hours,
            healthy=False,
            reason=f"Latest backup verification failed: {error}",
        )

    if not database_check.valid or not manifest_check.valid:
        return BackupStatus(
            backup_directory=str(directory),
            latest_backup_path=str(latest),
            latest_manifest_path=str(manifest),
            age_hours=age_hours,
            max_age_hours=max_age_hours,
            healthy=False,
            reason="Latest backup failed integrity or manifest checks.",
        )

    if age_hours > max_age_hours:
        return BackupStatus(
            backup_directory=str(directory),
            latest_backup_path=str(latest),
            latest_manifest_path=str(manifest),
            age_hours=age_hours,
            max_age_hours=max_age_hours,
            healthy=False,
            reason=(
                f"Latest backup is {age_hours:.2f} hours old; "
                f"maximum is {max_age_hours}."
            ),
        )

    return BackupStatus(
        backup_directory=str(directory),
        latest_backup_path=str(latest),
        latest_manifest_path=str(manifest),
        age_hours=age_hours,
        max_age_hours=max_age_hours,
        healthy=True,
        reason="Latest backup is recent and verified.",
    )


def result_as_dict(result: object) -> dict[str, Any]:
    return asdict(result)
