from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.db.leads import CRM_FINGERPRINT_BACKFILL_SENTINEL
from app.db.migrations import initialize_database
from app.sqlite import (
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_TIMEOUT_SECONDS,
    configure_busy_timeout,
    initialize_wal,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("MARK_OS_DB_PATH", str(DATA_DIR / "mark_os.db")))


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Open one transaction against the currently configured SQLite path."""
    # DB_PATH intentionally remains in this compatibility facade. Tests and
    # maintenance commands replace it with an isolated path at runtime.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        DB_PATH,
        timeout=SQLITE_TIMEOUT_SECONDS,
    )
    configure_busy_timeout(connection, SQLITE_BUSY_TIMEOUT_MS)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Run the domain-owned schema, migration, validation, and seed pipeline."""
    with get_db() as db:
        initialize_wal(db, DB_PATH)
        initialize_database(db)
