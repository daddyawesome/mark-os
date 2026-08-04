from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.db.schema import column_names, ensure_column, table_exists


@dataclass(frozen=True)
class OwnedTable:
    name: str
    parent_table: str | None = None
    parent_column: str | None = None
    parent_user_column: str = "user_id"


# Direct ownership is intentionally stored on child records too. This makes
# authorization checks simple and fail-closed during M9, while foreign-key
# relationships continue to preserve the domain hierarchy.
ADDITIVE_OWNED_TABLES = (
    OwnedTable("goals"),
    OwnedTable("projects"),
    OwnedTable("checkins"),
    OwnedTable("directions", "checkins", "checkin_id"),
    OwnedTable("game_history"),
    OwnedTable("tasks"),
    OwnedTable("quest_updates", "tasks", "task_id"),
    OwnedTable("xp_ledger", "tasks", "task_id"),
    OwnedTable("memories"),
    OwnedTable("timeline_events"),
    OwnedTable("chat_sessions"),
    OwnedTable("chat_messages", "chat_sessions", "session_id"),
    OwnedTable("agent_runs"),
    OwnedTable("agent_steps", "agent_runs", "run_id"),
)

SINGLETON_TABLES = ("profile", "game_state")

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_profile_user
ON profile(user_id);

CREATE INDEX IF NOT EXISTS idx_goals_user_status_priority
ON goals(user_id, status, priority DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_projects_user_status_priority
ON projects(user_id, status, priority DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_checkins_user_date
ON checkins(user_id, checkin_date DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_directions_user_checkin
ON directions(user_id, checkin_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_game_state_user
ON game_state(user_id);

CREATE INDEX IF NOT EXISTS idx_game_history_user_date
ON game_history(user_id, event_date DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_user_status_priority
ON tasks(user_id, status, priority DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_quest_updates_user_task
ON quest_updates(user_id, task_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_xp_ledger_user_created
ON xp_ledger(user_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_memories_user_active_importance
ON memories(user_id, active, importance DESC, updated_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_timeline_user_date
ON timeline_events(user_id, event_date DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_activity
ON chat_sessions(
    user_id,
    status,
    last_message_at DESC,
    updated_at DESC,
    id DESC
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_user_session
ON chat_messages(user_id, session_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_created
ON agent_runs(user_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_agent_steps_user_run
ON agent_steps(user_id, run_id, step_number);
"""


def find_owner_id(
    db: sqlite3.Connection,
) -> int | None:
    table = db.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'users'
        """
    ).fetchone()
    if table is None:
        return None

    row = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner'
        ORDER BY active DESC, id
        LIMIT 1
        """
    ).fetchone()
    return int(row["id"]) if row is not None else None


def get_owner_id(
    db: sqlite3.Connection,
    required: bool = True,
) -> int | None:
    owner_id = find_owner_id(db)

    if owner_id is None and required:
        raise RuntimeError(
            "Family ownership migration requires an owner account."
        )

    return owner_id


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
    return " ".join(row["sql"].lower().split())


def _rebuild_profile(
    db: sqlite3.Connection,
    owner_id: int,
) -> None:
    if not table_exists(db, "profile"):
        return

    columns = set(column_names(db, "profile"))
    sql = _table_sql(db, "profile")
    already_family_ready = (
        "user_id" in columns
        and "check (id = 1)" not in sql
        and "check(id = 1)" not in sql
    )
    if already_family_ready:
        return

    db.execute("ALTER TABLE profile RENAME TO profile_m8_legacy")
    db.execute(
        """
        CREATE TABLE profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            name TEXT NOT NULL,
            wealth_goal TEXT NOT NULL,
            weekday_hours TEXT NOT NULL,
            weekend_rule TEXT NOT NULL,
            strongest_skills TEXT NOT NULL,
            primary_blocker TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    legacy_columns = set(column_names(db, "profile_m8_legacy"))
    if "user_id" in legacy_columns:
        db.execute(
            """
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
                COALESCE(user_id, ?),
                name,
                wealth_goal,
                weekday_hours,
                weekend_rule,
                strongest_skills,
                primary_blocker,
                updated_at
            FROM profile_m8_legacy
            ORDER BY id
            """,
            (owner_id,),
        )
    else:
        db.execute(
            """
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
                ?,
                name,
                wealth_goal,
                weekday_hours,
                weekend_rule,
                strongest_skills,
                primary_blocker,
                updated_at
            FROM profile_m8_legacy
            ORDER BY id
            """,
            (owner_id,),
        )

    db.execute("DROP TABLE profile_m8_legacy")


def _rebuild_game_state(
    db: sqlite3.Connection,
    owner_id: int,
) -> None:
    if not table_exists(db, "game_state"):
        return

    columns = set(column_names(db, "game_state"))
    sql = _table_sql(db, "game_state")
    already_family_ready = (
        "user_id" in columns
        and "check (id = 1)" not in sql
        and "check(id = 1)" not in sql
    )
    if already_family_ready:
        return

    required_columns = {
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
    missing = required_columns - columns
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise RuntimeError(
            "Cannot migrate game_state ownership; missing columns: "
            f"{missing_names}"
        )

    db.execute(
        "ALTER TABLE game_state RENAME TO game_state_m8_legacy"
    )
    db.execute(
        """
        CREATE TABLE game_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            level INTEGER NOT NULL DEFAULT 1 CHECK(level >= 1),
            xp_total INTEGER,
            xp_into_level INTEGER NOT NULL DEFAULT 0,
            character_class TEXT NOT NULL,
            threshold_mode TEXT NOT NULL DEFAULT 'hidden',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source TEXT NOT NULL DEFAULT 'system',
            notes TEXT NOT NULL DEFAULT '',
            last_level_up_at TEXT
        )
        """
    )

    legacy_columns = set(column_names(db, "game_state_m8_legacy"))
    user_expression = (
        "COALESCE(user_id, ?)"
        if "user_id" in legacy_columns
        else "?"
    )
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
        FROM game_state_m8_legacy
        ORDER BY id
        """,
        (owner_id,),
    )
    db.execute("DROP TABLE game_state_m8_legacy")


def _add_user_columns(db: sqlite3.Connection) -> None:
    for owned_table in ADDITIVE_OWNED_TABLES:
        if not table_exists(db, owned_table.name):
            continue
        ensure_column(
            db,
            owned_table.name,
            "user_id",
            "INTEGER",
        )


def _backfill_direct_tables(
    db: sqlite3.Connection,
    owner_id: int,
) -> None:
    direct_tables = (
        "goals",
        "projects",
        "checkins",
        "game_history",
        "tasks",
        "memories",
        "timeline_events",
        "chat_sessions",
    )
    for table_name in direct_tables:
        if table_exists(db, table_name):
            db.execute(
                f"""
                UPDATE {table_name}
                SET user_id = ?
                WHERE user_id IS NULL
                """,
                (owner_id,),
            )

    # Agent runs may have a chat session. Preserve that owner when available,
    # otherwise assign legacy or detached runs to Mark.
    if table_exists(db, "agent_runs"):
        db.execute(
            """
            UPDATE agent_runs
            SET user_id = COALESCE(
                (
                    SELECT chat_sessions.user_id
                    FROM chat_sessions
                    WHERE chat_sessions.id = agent_runs.session_id
                ),
                ?
            )
            WHERE user_id IS NULL
            """,
            (owner_id,),
        )


def _backfill_child_tables(
    db: sqlite3.Connection,
    owner_id: int,
) -> None:
    child_updates = (
        (
            "directions",
            """
            UPDATE directions
            SET user_id = COALESCE(
                (
                    SELECT checkins.user_id
                    FROM checkins
                    WHERE checkins.id = directions.checkin_id
                ),
                ?
            )
            WHERE user_id IS NULL
            """,
        ),
        (
            "quest_updates",
            """
            UPDATE quest_updates
            SET user_id = COALESCE(
                (
                    SELECT tasks.user_id
                    FROM tasks
                    WHERE tasks.id = quest_updates.task_id
                ),
                ?
            )
            WHERE user_id IS NULL
            """,
        ),
        (
            "xp_ledger",
            """
            UPDATE xp_ledger
            SET user_id = COALESCE(
                (
                    SELECT tasks.user_id
                    FROM tasks
                    WHERE tasks.id = xp_ledger.task_id
                ),
                ?
            )
            WHERE user_id IS NULL
            """,
        ),
        (
            "chat_messages",
            """
            UPDATE chat_messages
            SET user_id = COALESCE(
                (
                    SELECT chat_sessions.user_id
                    FROM chat_sessions
                    WHERE chat_sessions.id = chat_messages.session_id
                ),
                ?
            )
            WHERE user_id IS NULL
            """,
        ),
        (
            "agent_steps",
            """
            UPDATE agent_steps
            SET user_id = COALESCE(
                (
                    SELECT agent_runs.user_id
                    FROM agent_runs
                    WHERE agent_runs.id = agent_steps.run_id
                ),
                ?
            )
            WHERE user_id IS NULL
            """,
        ),
    )

    for table_name, statement in child_updates:
        if table_exists(db, table_name):
            db.execute(statement, (owner_id,))


def backfill_owner(db: sqlite3.Connection) -> None:
    owner_id = get_owner_id(db, required=False)
    if owner_id is None:
        return

    if table_exists(db, "profile"):
        db.execute(
            """
            UPDATE profile
            SET user_id = ?
            WHERE user_id IS NULL
            """,
            (owner_id,),
        )

    if table_exists(db, "game_state"):
        db.execute(
            """
            UPDATE game_state
            SET user_id = ?
            WHERE user_id IS NULL
            """,
            (owner_id,),
        )

    _backfill_direct_tables(db, owner_id)
    _backfill_child_tables(db, owner_id)


def ensure_singleton_user_columns(
    db: sqlite3.Connection,
) -> None:
    for table_name in SINGLETON_TABLES:
        if not table_exists(db, table_name):
            continue
        if "user_id" in set(column_names(db, table_name)):
            continue
        db.execute(
            f"ALTER TABLE {table_name} "
            "ADD COLUMN user_id INTEGER"
        )


def migrate(db: sqlite3.Connection) -> None:
    _add_user_columns(db)
    ensure_singleton_user_columns(db)

    owner_id = find_owner_id(db)
    if owner_id is None:
        return

    _rebuild_profile(db, owner_id)
    _rebuild_game_state(db, owner_id)
    _add_user_columns(db)
    backfill_owner(db)


def create_indexes(db: sqlite3.Connection) -> None:
    required_tables = set(SINGLETON_TABLES)
    required_tables.update(
        owned_table.name
        for owned_table in ADDITIVE_OWNED_TABLES
    )

    for table_name in required_tables:
        if not table_exists(db, table_name):
            return
        if "user_id" not in set(column_names(db, table_name)):
            return

    db.executescript(INDEX_SQL)


def validate(db: sqlite3.Connection) -> None:
    owner_id = find_owner_id(db)
    if owner_id is None:
        return
    owner_id = get_owner_id(db, required=False)
    if owner_id is None:
        return
    expected_tables = set(SINGLETON_TABLES)
    expected_tables.update(
        owned_table.name for owned_table in ADDITIVE_OWNED_TABLES
    )

    for table_name in sorted(expected_tables):
        if not table_exists(db, table_name):
            raise RuntimeError(
                f"Family ownership table is missing: {table_name}"
            )

        columns = {
            row["name"]: row
            for row in db.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()
        }
        user_column = columns.get("user_id")
        if user_column is None:
            raise RuntimeError(
                f"Family ownership column is missing: {table_name}.user_id"
            )
        if user_column["type"].upper() != "INTEGER":
            raise RuntimeError(
                f"{table_name}.user_id must be INTEGER"
            )

        null_count = db.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE user_id IS NULL
            """
        ).fetchone()[0]
        if null_count:
            raise RuntimeError(
                f"{table_name} contains {null_count} unowned rows"
            )

        orphan_count = db.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            LEFT JOIN users ON users.id = {table_name}.user_id
            WHERE users.id IS NULL
            """
        ).fetchone()[0]
        if orphan_count:
            raise RuntimeError(
                f"{table_name} contains {orphan_count} invalid owners"
            )

    profile_sql = _table_sql(db, "profile")
    game_state_sql = _table_sql(db, "game_state")
    for table_name, sql in (
        ("profile", profile_sql),
        ("game_state", game_state_sql),
    ):
        if "check (id = 1)" in sql or "check(id = 1)" in sql:
            raise RuntimeError(
                f"{table_name} still has a single-user ID constraint"
            )

    duplicate_profiles = db.execute(
        """
        SELECT user_id
        FROM profile
        GROUP BY user_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    duplicate_game_states = db.execute(
        """
        SELECT user_id
        FROM game_state
        GROUP BY user_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    if duplicate_profiles or duplicate_game_states:
        raise RuntimeError(
            "Each user must have at most one profile and game state."
        )

    # M8 must never manufacture records for newly-created family members.
