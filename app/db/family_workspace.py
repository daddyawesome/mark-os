from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from app.db.schema import column_names, table_exists


PERSONAL_ROLES = ("owner", "member")
PROJECT_UNIQUE_INDEX = "ux_projects_user_name"
MEMORY_UNIQUE_INDEX = "ux_memories_user_key"


@dataclass(frozen=True)
class WorkspaceResult:
    user_id: int
    profile_created: bool
    game_state_created: bool


def _positive_id(value: int, field_name: str = "User ID") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _table_sql(db: sqlite3.Connection, table_name: str) -> str:
    row = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    if row is None or row["sql"] is None:
        raise RuntimeError(f"Required table is missing: {table_name}")
    return str(row["sql"])


def _index_columns(
    db: sqlite3.Connection,
    index_name: str,
) -> list[str]:
    return [
        str(row["name"])
        for row in db.execute(
            f'PRAGMA index_info("{index_name}")'
        ).fetchall()
    ]


def _has_single_column_unique(
    db: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    for row in db.execute(
        f'PRAGMA index_list("{table_name}")'
    ).fetchall():
        if not bool(row["unique"]):
            continue
        if _index_columns(db, str(row["name"])) == [column_name]:
            return True
    return False


def _remove_global_unique(
    create_sql: str,
    column_name: str,
) -> str:
    escaped = re.escape(column_name)

    inline_patterns = (
        re.compile(
            rf"(\b{escaped}\b\s+TEXT\s+NOT\s+NULL)\s+UNIQUE\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(\b{escaped}\b\s+TEXT\s+COLLATE\s+\w+\s+NOT\s+NULL)"
            rf"\s+UNIQUE\b",
            re.IGNORECASE,
        ),
    )
    transformed = create_sql
    for pattern in inline_patterns:
        transformed, count = pattern.subn(r"\1", transformed, count=1)
        if count:
            return transformed

    table_unique_patterns = (
        re.compile(
            rf",\s*UNIQUE\s*\(\s*{escaped}\s*\)",
            re.IGNORECASE,
        ),
        re.compile(
            rf"UNIQUE\s*\(\s*{escaped}\s*\)\s*,",
            re.IGNORECASE,
        ),
    )
    for pattern in table_unique_patterns:
        transformed, count = pattern.subn("", transformed, count=1)
        if count:
            return transformed

    raise RuntimeError(
        f"Could not remove the legacy UNIQUE constraint from {column_name}."
    )


def _named_index_sql(
    db: sqlite3.Connection,
    table_name: str,
) -> list[tuple[str, str]]:
    rows = db.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type = 'index'
          AND tbl_name = ?
          AND sql IS NOT NULL
        ORDER BY name
        """,
        (table_name,),
    ).fetchall()
    return [(str(row["name"]), str(row["sql"])) for row in rows]


def _rebuild_without_global_unique(
    db: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
) -> None:
    if not table_exists(db, table_name):
        return
    if "user_id" not in set(column_names(db, table_name)):
        return
    if not _has_single_column_unique(db, table_name, column_name):
        return

    legacy_name = f"{table_name}_m10_legacy"
    if table_exists(db, legacy_name):
        raise RuntimeError(
            f"Interrupted M10 migration detected: {legacy_name} exists."
        )

    original_sql = _table_sql(db, table_name)
    replacement_sql = _remove_global_unique(original_sql, column_name)
    indexes = _named_index_sql(db, table_name)
    columns = list(column_names(db, table_name))
    quoted_columns = ", ".join(f'"{name}"' for name in columns)

    legacy_setting = int(
        db.execute("PRAGMA legacy_alter_table").fetchone()[0]
    )
    db.execute("PRAGMA legacy_alter_table = ON")
    try:
        db.execute(
            f'ALTER TABLE "{table_name}" RENAME TO "{legacy_name}"'
        )
        db.execute(replacement_sql)
        db.execute(
            f'INSERT INTO "{table_name}" ({quoted_columns}) '
            f'SELECT {quoted_columns} FROM "{legacy_name}"'
        )
        db.execute(f'DROP TABLE "{legacy_name}"')

        for index_name, index_sql in indexes:
            # Do not recreate the old global single-column unique index.
            if index_name in {PROJECT_UNIQUE_INDEX, MEMORY_UNIQUE_INDEX}:
                continue
            db.execute(index_sql)
    finally:
        db.execute(
            "PRAGMA legacy_alter_table = "
            + ("ON" if legacy_setting else "OFF")
        )


def _has_legacy_singleton_check(
    db: sqlite3.Connection,
    table_name: str,
) -> bool:
    if not table_exists(db, table_name):
        return False
    normalized = " ".join(_table_sql(db, table_name).lower().split())
    return re.search(
        r"check\s*\(\s*id\s*=\s*1\s*\)",
        normalized,
    ) is not None


def _rebuild_profile_singleton(db: sqlite3.Connection) -> None:
    if not _has_legacy_singleton_check(db, "profile"):
        return

    legacy_name = "profile_m10_singleton_legacy"
    if table_exists(db, legacy_name):
        raise RuntimeError(
            f"Interrupted M10 migration detected: {legacy_name} exists."
        )

    required = {
        "id",
        "name",
        "wealth_goal",
        "weekday_hours",
        "weekend_rule",
        "strongest_skills",
        "primary_blocker",
        "updated_at",
    }
    existing = set(column_names(db, "profile"))
    missing = required - existing
    if missing:
        raise RuntimeError(
            "Cannot rebuild profile; missing columns: "
            + ", ".join(sorted(missing))
        )

    db.execute(
        f'ALTER TABLE "profile" RENAME TO "{legacy_name}"'
    )
    db.execute(
        """
        CREATE TABLE profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            name TEXT NOT NULL,
            wealth_goal TEXT NOT NULL,
            weekday_hours TEXT NOT NULL,
            weekend_rule TEXT NOT NULL,
            strongest_skills TEXT NOT NULL,
            primary_blocker TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    user_expression = "user_id" if "user_id" in existing else "NULL"
    db.execute(
        f"""
        INSERT INTO profile (
            id,
            user_id,
            name,
            wealth_goal,
            weekday_hours,
            weekend_rule,
            strongest_skills,
            primary_blocker,
            updated_at
        )
        SELECT
            id,
            {user_expression},
            name,
            wealth_goal,
            weekday_hours,
            weekend_rule,
            strongest_skills,
            primary_blocker,
            updated_at
        FROM "{legacy_name}"
        ORDER BY id
        """
    )
    db.execute(f'DROP TABLE "{legacy_name}"')


def _rebuild_game_state_singleton(db: sqlite3.Connection) -> None:
    if not _has_legacy_singleton_check(db, "game_state"):
        return

    legacy_name = "game_state_m10_singleton_legacy"
    if table_exists(db, legacy_name):
        raise RuntimeError(
            f"Interrupted M10 migration detected: {legacy_name} exists."
        )

    required = {
        "id",
        "level",
        "xp_total",
        "xp_into_level",
        "character_class",
        "threshold_mode",
        "updated_at",
        "source",
        "notes",
        "last_level_up_at",
    }
    existing = set(column_names(db, "game_state"))
    missing = required - existing
    if missing:
        raise RuntimeError(
            "Cannot rebuild game_state; missing columns: "
            + ", ".join(sorted(missing))
        )

    db.execute(
        f'ALTER TABLE "game_state" RENAME TO "{legacy_name}"'
    )
    db.execute(
        """
        CREATE TABLE game_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            level INTEGER NOT NULL DEFAULT 1 CHECK(level >= 1),
            xp_total INTEGER,
            xp_into_level INTEGER NOT NULL DEFAULT 0,
            character_class TEXT NOT NULL,
            threshold_mode TEXT NOT NULL DEFAULT 'hidden',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source TEXT NOT NULL DEFAULT 'system',
            notes TEXT NOT NULL DEFAULT '',
            last_level_up_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    user_expression = "user_id" if "user_id" in existing else "NULL"
    db.execute(
        f"""
        INSERT INTO game_state (
            id,
            user_id,
            level,
            xp_total,
            xp_into_level,
            character_class,
            threshold_mode,
            updated_at,
            source,
            notes,
            last_level_up_at
        )
        SELECT
            id,
            {user_expression},
            level,
            xp_total,
            xp_into_level,
            character_class,
            threshold_mode,
            updated_at,
            source,
            notes,
            last_level_up_at
        FROM "{legacy_name}"
        ORDER BY id
        """
    )
    db.execute(f'DROP TABLE "{legacy_name}"')

def create_indexes(db: sqlite3.Connection) -> None:
    if table_exists(db, "projects") and "user_id" in set(
        column_names(db, "projects")
    ):
        try:
            db.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {PROJECT_UNIQUE_INDEX}
                ON projects(user_id, name)
                """
            )
        except sqlite3.IntegrityError as exc:
            raise RuntimeError(
                "Duplicate project names exist for the same user. "
                "Rename the duplicates before completing M10."
            ) from exc

    if table_exists(db, "memories") and "user_id" in set(
        column_names(db, "memories")
    ):
        try:
            db.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {MEMORY_UNIQUE_INDEX}
                ON memories(user_id, memory_key)
                """
            )
        except sqlite3.IntegrityError as exc:
            raise RuntimeError(
                "Duplicate memory keys exist for the same user. "
                "Repair the duplicates before completing M10."
            ) from exc





def migrate(db: sqlite3.Connection) -> None:
    """Complete the M10 schema rebuilds safely.

    The profile and game_state tables must lose the old CHECK(id = 1)
    constraint even when startup has no owner yet. Existing nullable ownership
    is preserved and can be claimed or backfilled when the owner is created.
    """
    singleton_rebuild_needed = any(
        _has_legacy_singleton_check(db, table_name)
        for table_name in ("profile", "game_state")
    )
    uniqueness_rebuild_needed = any(
        table_exists(db, table_name)
        and "user_id" in set(column_names(db, table_name))
        and _has_single_column_unique(db, table_name, column_name)
        for table_name, column_name in (
            ("projects", "name"),
            ("memories", "memory_key"),
        )
    )

    if not singleton_rebuild_needed and not uniqueness_rebuild_needed:
        create_indexes(db)
        return

    db.commit()
    foreign_keys_enabled = bool(
        db.execute("PRAGMA foreign_keys").fetchone()[0]
    )
    legacy_alter_enabled = bool(
        db.execute("PRAGMA legacy_alter_table").fetchone()[0]
    )

    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("PRAGMA legacy_alter_table = ON")
    try:
        _rebuild_profile_singleton(db)
        _rebuild_game_state_singleton(db)
        _rebuild_without_global_unique(
            db,
            table_name="projects",
            column_name="name",
        )
        _rebuild_without_global_unique(
            db,
            table_name="memories",
            column_name="memory_key",
        )

        from app.db import family_integrity, family_ownership

        family_ownership.create_indexes(db)
        create_indexes(db)

        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                "Foreign-key violations were found during the M10 rebuild."
            )

        family_integrity.create_triggers(db)
        family_integrity.validate_triggers(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute(
            "PRAGMA legacy_alter_table = "
            + ("ON" if legacy_alter_enabled else "OFF")
        )
        db.execute(
            "PRAGMA foreign_keys = "
            + ("ON" if foreign_keys_enabled else "OFF")
        )





def ensure_personal_workspace(
    db: sqlite3.Connection,
    user_id: int,
) -> WorkspaceResult:
    safe_user_id = _positive_id(user_id)
    user = db.execute(
        """
        SELECT id, display_name, role, active
        FROM users
        WHERE id = ?
        """,
        (safe_user_id,),
    ).fetchone()
    if user is None:
        raise ValueError("User not found.")
    if not bool(user["active"]) or user["role"] not in PERSONAL_ROLES:
        raise PermissionError(
            "A personal workspace requires an active owner or member."
        )

    profile_before = db.execute(
        "SELECT id FROM profile WHERE user_id = ?",
        (safe_user_id,),
    ).fetchone()
    profile_created = profile_before is None
    if profile_before is None:
        unowned_profile = db.execute(
            """
            SELECT id
            FROM profile
            WHERE user_id IS NULL OR user_id = 0
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        if unowned_profile is not None:
            db.execute(
                """
                UPDATE profile
                SET user_id = ?,
                    name = CASE
                        WHEN TRIM(name) = '' THEN ?
                        ELSE name
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    safe_user_id,
                    str(user["display_name"]),
                    int(unowned_profile["id"]),
                ),
            )
        else:
            db.execute(
                """
                INSERT INTO profile (
                    user_id,
                    name,
                    wealth_goal,
                    weekday_hours,
                    weekend_rule,
                    strongest_skills,
                    primary_blocker
                )
                VALUES (?, ?, '', '', '', '', '')
                """,
                (safe_user_id, str(user["display_name"])),
            )

    game_before = db.execute(
        "SELECT id FROM game_state WHERE user_id = ?",
        (safe_user_id,),
    ).fetchone()
    game_state_created = game_before is None
    if game_before is None:
        unowned_game = db.execute(
            """
            SELECT id
            FROM game_state
            WHERE user_id IS NULL OR user_id = 0
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        if unowned_game is not None:
            db.execute(
                """
                UPDATE game_state
                SET user_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (safe_user_id, int(unowned_game["id"])),
            )
        else:
            db.execute(
                """
                INSERT INTO game_state (
                    user_id,
                    level,
                    xp_total,
                    xp_into_level,
                    character_class,
                    threshold_mode,
                    source,
                    notes
                )
                VALUES (?, 1, 0, 0, 'Explorer', 'hidden',
                        'family_workspace', '')
                """,
                (safe_user_id,),
            )

    return WorkspaceResult(
        user_id=safe_user_id,
        profile_created=profile_created,
        game_state_created=game_state_created,
    )


def ensure_all_workspaces(db: sqlite3.Connection) -> None:
    if not table_exists(db, "users"):
        return
    rows = db.execute(
        """
        SELECT id
        FROM users
        WHERE active = 1
          AND role IN ('owner', 'member')
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        ensure_personal_workspace(db, int(row["id"]))


def _validate_index(
    db: sqlite3.Connection,
    *,
    table_name: str,
    index_name: str,
    expected_columns: list[str],
) -> None:
    indexes = {
        str(row["name"]): row
        for row in db.execute(
            f'PRAGMA index_list("{table_name}")'
        ).fetchall()
    }
    index = indexes.get(index_name)
    if index is None or not bool(index["unique"]):
        raise RuntimeError(
            f"M10 unique index is missing or weakened: {index_name}"
        )
    if _index_columns(db, index_name) != expected_columns:
        raise RuntimeError(
            f"M10 unique index has wrong columns: {index_name}"
        )


def validate(db: sqlite3.Connection) -> None:
    for table_name, column_name, index_name in (
        ("projects", "name", PROJECT_UNIQUE_INDEX),
        ("memories", "memory_key", MEMORY_UNIQUE_INDEX),
    ):
        if not table_exists(db, table_name):
            raise RuntimeError(f"M10 table is missing: {table_name}")
        if "user_id" not in set(column_names(db, table_name)):
            # Ownerless partial migration fixtures intentionally stop here.
            return
        if _has_single_column_unique(db, table_name, column_name):
            raise RuntimeError(
                f"{table_name}.{column_name} is still globally unique."
            )
        _validate_index(
            db,
            table_name=table_name,
            index_name=index_name,
            expected_columns=["user_id", column_name],
        )

    missing = db.execute(
        """
        SELECT
            u.id,
            u.username,
            CASE WHEN p.id IS NULL THEN 1 ELSE 0 END AS missing_profile,
            CASE WHEN g.id IS NULL THEN 1 ELSE 0 END AS missing_game_state
        FROM users AS u
        LEFT JOIN profile AS p ON p.user_id = u.id
        LEFT JOIN game_state AS g ON g.user_id = u.id
        WHERE u.active = 1
          AND u.role IN ('owner', 'member')
          AND (p.id IS NULL OR g.id IS NULL)
        ORDER BY u.id
        """
    ).fetchall()
    if missing:
        usernames = ", ".join(str(row["username"]) for row in missing)
        raise RuntimeError(
            "Active personal users are missing workspaces: " + usernames
        )

    violations = db.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            "Foreign-key violations remain after M10 workspace migration."
        )
