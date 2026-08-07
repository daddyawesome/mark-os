from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final


SQLITE_TIMEOUT_SECONDS: Final[int] = 30
SQLITE_BUSY_TIMEOUT_MS: Final[int] = 30_000
OPERATIONS_SQLITE_TIMEOUT_SECONDS: Final[int] = 3
OPERATIONS_SQLITE_BUSY_TIMEOUT_MS: Final[int] = 3_000


def configure_busy_timeout(
    connection: sqlite3.Connection,
    busy_timeout_ms: int,
) -> None:
    connection.execute(
        f"PRAGMA busy_timeout = {busy_timeout_ms}"
    )


def enable_wal(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode = WAL").fetchone()


def initialize_wal(
    connection: sqlite3.Connection,
    path: str | Path,
) -> None:
    if not is_memory_database(path):
        enable_wal(connection)


def is_memory_database(path: str | Path) -> bool:
    value = str(path)
    return value == ":memory:" or (
        value.startswith("file:") and "mode=memory" in value
    )