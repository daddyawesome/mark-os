from __future__ import annotations

import sqlite3

from app.db import agent_audit, chat, checkins, goals, leads, memory, quests, users


# Keep table creation and ordinary-index creation in the same two executescript
# boundaries used by the original monolithic initializer. This preserves SQLite's
# transaction behavior while each domain owns its own SQL and validation rules.
SCHEMA_SQL = "\n".join(
    (
        users.SCHEMA_SQL,
        goals.SCHEMA_SQL,
        checkins.SCHEMA_SQL,
        quests.GAME_SCHEMA_SQL,
        memory.SCHEMA_SQL,
        quests.QUEST_SCHEMA_SQL,
        chat.SCHEMA_SQL,
        agent_audit.SCHEMA_SQL,
        leads.SCHEMA_SQL,
    )
)

INDEX_SQL = "\n".join(
    (
        users.INDEX_SQL,
        checkins.INDEX_SQL,
        memory.INDEX_SQL,
        quests.INDEX_SQL,
        chat.INDEX_SQL,
        agent_audit.INDEX_SQL,
        leads.INDEX_SQL,
    )
)


def initialize_database(db: sqlite3.Connection) -> None:
    """Create, migrate, validate, and seed every persistent domain."""
    db.executescript(SCHEMA_SQL)

    chat.validate_schema(db)
    agent_audit.validate_schema(db)
    leads.migrate_request_fingerprint(db)
    leads.migrate_ownership(db)
    leads.validate_schema(db)
    users.validate_schema(db)

    # Safe additive migrations for already-live SQLite databases.
    quests.migrate_game_state(db)
    goals.migrate(db)
    quests.migrate_quest_tables(db)
    checkins.migrate(db)
    memory.migrate(db)

    # Ordinary indexes must be created only after legacy columns exist.
    db.executescript(INDEX_SQL)

    quests.create_unique_indexes(db)
    chat.create_unique_indexes(db)
    agent_audit.create_unique_indexes(db)
    leads.create_unique_indexes(db)

    chat.validate_indexes(db)
    agent_audit.validate_indexes(db)
    leads.validate_indexes(db)
    users.validate_indexes(db)

    quests.backfill(db)
    goals.seed(db)
    quests.seed(db)
    memory.seed(db)
    users.bootstrap_owner_from_environment(db)
