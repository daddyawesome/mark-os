from __future__ import annotations

import sqlite3
from pathlib import Path

from app import database
from app.services import database_backup, operations_monitoring
from app.sqlite import (
    OPERATIONS_SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_BUSY_TIMEOUT_MS,
    initialize_wal,
)


def _pragma_value(
    connection: sqlite3.Connection,
    pragma: str,
):
    return connection.execute(
        f"PRAGMA {pragma}"
    ).fetchone()[0]


def _create_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)"
    )
    connection.commit()
    connection.close()


def test_writable_initialization_enables_wal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "primary.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    with database.get_db() as connection:
        assert _pragma_value(connection, "journal_mode") == "wal"
        assert _pragma_value(connection, "busy_timeout") == (
            SQLITE_BUSY_TIMEOUT_MS
        )


def test_wal_initialization_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "idempotent.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        initialize_wal(connection, database_path)
        initialize_wal(connection, database_path)
        assert _pragma_value(connection, "journal_mode") == "wal"
    finally:
        connection.close()


def test_wal_initialization_skips_memory_database() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        initialize_wal(connection, ":memory:")
        assert _pragma_value(connection, "journal_mode") == "memory"
    finally:
        connection.close()


def test_backup_connections_configure_busy_timeout(tmp_path: Path) -> None:
    database_path = tmp_path / "backup.sqlite3"
    _create_database(database_path)

    read_connection = database_backup._read_only_connection(database_path)
    write_connection = database_backup._write_connection(database_path)
    try:
        assert _pragma_value(read_connection, "busy_timeout") == (
            SQLITE_BUSY_TIMEOUT_MS
        )
        assert _pragma_value(write_connection, "busy_timeout") == (
            SQLITE_BUSY_TIMEOUT_MS
        )
    finally:
        read_connection.close()
        write_connection.close()


def test_operations_monitoring_connection_configures_short_busy_timeout(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitoring.sqlite3"
    _create_database(database_path)

    connection = operations_monitoring._read_only_connection(database_path)
    try:
        assert _pragma_value(connection, "busy_timeout") == (
            OPERATIONS_SQLITE_BUSY_TIMEOUT_MS
        )
    finally:
        connection.close()


def test_database_initialization_remains_functional(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / "initialized.sqlite3",
    )
    database.init_db()

    with database.get_db() as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'users'"
        ).fetchone()[0] == 1