from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from app.services.database_backup import (
    check_backup_status,
    create_sqlite_backup,
    manifest_path_for_backup,
    restore_sqlite_backup,
    verify_backup_manifest,
    verify_sqlite_database,
)
from tools.encrypt_backup import build_gpg_command


def _create_sample_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE
        );

        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        INSERT INTO users (id, username)
        VALUES (1, 'mark');

        INSERT INTO tasks (id, user_id, title)
        VALUES (1, 1, 'Verify the backup');
        """
    )
    connection.commit()
    connection.close()


def test_backup_restore_and_manifest_round_trip(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite3"
    backup_directory = tmp_path / "backups"
    restored = tmp_path / "restored.sqlite3"
    _create_sample_database(source)

    backup = create_sqlite_backup(
        source,
        backup_directory,
        keep_last=5,
    )
    backup_path = Path(backup.backup_path)
    manifest_path = Path(backup.manifest_path)

    assert backup_path.exists()
    assert manifest_path.exists()
    assert Path(backup.event_log_path).exists()
    assert backup.quick_check == "ok"
    assert backup.foreign_key_errors == 0

    manifest_check = verify_backup_manifest(
        backup_path,
        manifest_path,
    )
    assert manifest_check.valid is True

    restore = restore_sqlite_backup(
        backup_path,
        restored,
        manifest_path=manifest_path,
    )
    assert restore.quick_check == "ok"
    assert restore.foreign_key_errors == 0

    connection = sqlite3.connect(restored)
    row = connection.execute(
        """
        SELECT users.username, tasks.title
        FROM tasks
        JOIN users ON users.id = tasks.user_id
        """
    ).fetchone()
    connection.close()
    assert row == ("mark", "Verify the backup")


def test_backup_event_log_records_success(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite3"
    backup_directory = tmp_path / "backups"
    _create_sample_database(source)

    result = create_sqlite_backup(source, backup_directory)
    lines = Path(result.event_log_path).read_text(
        encoding="utf-8"
    ).splitlines()
    payload = json.loads(lines[-1])
    assert payload["status"] == "succeeded"
    assert payload["sha256"] == result.sha256


def test_failed_backup_is_visible_in_event_log(
    tmp_path: Path,
) -> None:
    backup_directory = tmp_path / "backups"

    with pytest.raises(FileNotFoundError):
        create_sqlite_backup(
            tmp_path / "missing.sqlite3",
            backup_directory,
        )

    event_log = backup_directory / "backup_events.jsonl"
    payload = json.loads(
        event_log.read_text(encoding="utf-8").splitlines()[-1]
    )
    assert payload["status"] == "failed"
    assert payload["error_type"] == "FileNotFoundError"


def test_retention_never_deletes_live_database(
    tmp_path: Path,
) -> None:
    backup_directory = tmp_path / "backups"
    source = backup_directory / "mark_os_0000.sqlite3"
    _create_sample_database(source)

    for _ in range(4):
        create_sqlite_backup(
            source,
            backup_directory,
            backup_prefix="mark_os",
            keep_last=1,
        )

    generated = [
        path
        for path in backup_directory.glob("mark_os_*.sqlite3")
        if path.resolve() != source.resolve()
    ]
    assert source.exists()
    assert len(generated) == 1


def test_manifest_tampering_is_detected(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite3"
    backup_directory = tmp_path / "backups"
    _create_sample_database(source)
    result = create_sqlite_backup(source, backup_directory)

    manifest = Path(result.manifest_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    check = verify_backup_manifest(result.backup_path, manifest)
    assert check.valid is False
    with pytest.raises(RuntimeError, match="manifest checksum"):
        restore_sqlite_backup(
            result.backup_path,
            tmp_path / "restored.sqlite3",
            manifest_path=manifest,
        )


def test_restore_requires_new_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite3"
    backup_directory = tmp_path / "backups"
    _create_sample_database(source)
    result = create_sqlite_backup(source, backup_directory)

    with pytest.raises(ValueError, match="new database file"):
        restore_sqlite_backup(
            result.backup_path,
            result.backup_path,
        )


def test_backup_status_reports_fresh_and_stale(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite3"
    backup_directory = tmp_path / "backups"
    _create_sample_database(source)
    result = create_sqlite_backup(source, backup_directory)

    fresh = check_backup_status(
        backup_directory,
        max_age_hours=1,
    )
    assert fresh.healthy is True

    old_timestamp = Path(result.backup_path).stat().st_mtime - 7200
    os.utime(result.backup_path, (old_timestamp, old_timestamp))
    stale = check_backup_status(
        backup_directory,
        max_age_hours=1,
    )
    assert stale.healthy is False
    assert "hours old" in stale.reason


def test_verify_reports_valid_database(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _create_sample_database(source)
    result = verify_sqlite_database(source)
    assert result.valid is True
    assert result.quick_check == "ok"
    assert result.foreign_key_errors == 0
    assert len(result.sha256) == 64


def test_manifest_path_is_portable(tmp_path: Path) -> None:
    backup = tmp_path / "mark_os.sqlite3"
    assert manifest_path_for_backup(backup).name == (
        "mark_os.sqlite3.json"
    )


def test_gpg_commands_support_symmetric_and_recipient_modes(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "backup.sqlite3"
    output = tmp_path / "backup.sqlite3.gpg"

    symmetric = build_gpg_command(
        backup=backup,
        output=output,
        recipient=None,
    )
    assert "--symmetric" in symmetric
    assert "AES256" in symmetric
    assert "--no-symkey-cache" in symmetric

    recipient = build_gpg_command(
        backup=backup,
        output=output,
        recipient="mark@example.com",
    )
    assert "--encrypt" in recipient
    assert "--recipient" in recipient
    assert "mark@example.com" in recipient
