from __future__ import annotations

import sqlite3

from app.db import (
    agent_audit,
    chat,
    checkins,
    family_ownership,
    family_workspace,
    goals,
    lead_research,
    leads,
    memory,
    organizations,
    playbooks,
    quests,
    relationship_manager,
    users,
)
from app.db import family_integrity
from app.db import lead_activities


# Keep table creation and ordinary-index creation in the same two executescript
# boundaries used by the original monolithic initializer. This preserves SQLite's
# transaction behavior while each domain owns its own SQL and validation rules.
SCHEMA_SQL = "\n".join(
    (
        users.SCHEMA_SQL,
        organizations.SCHEMA_SQL,
        playbooks.SCHEMA_SQL,
        goals.SCHEMA_SQL,
        checkins.SCHEMA_SQL,
        quests.GAME_SCHEMA_SQL,
        memory.SCHEMA_SQL,
        quests.QUEST_SCHEMA_SQL,
        chat.SCHEMA_SQL,
        agent_audit.SCHEMA_SQL,
        leads.SCHEMA_SQL,
        lead_research.SCHEMA_SQL,
        relationship_manager.SCHEMA_SQL,
        lead_activities.SCHEMA_SQL,
    )
)

INDEX_SQL = "\n".join(
    (
        users.INDEX_SQL,
        organizations.INDEX_SQL,
        playbooks.INDEX_SQL,
        checkins.INDEX_SQL,
        memory.INDEX_SQL,
        quests.INDEX_SQL,
        chat.INDEX_SQL,
        agent_audit.INDEX_SQL,
        leads.INDEX_SQL,
        lead_research.INDEX_SQL,
        relationship_manager.INDEX_SQL,
        lead_activities.INDEX_SQL,
    )
)


def initialize_database(db: sqlite3.Connection) -> None:
    """Create, migrate, validate, and seed every persistent domain."""
    family_integrity.drop_triggers(db)
    db.executescript(SCHEMA_SQL)

    chat.validate_schema(db)
    agent_audit.validate_schema(db)
    organizations.validate_schema(db)
    organizations.seed(db)
    leads.migrate_request_fingerprint(db)
    leads.migrate_ownership(db)
    users.migrate(db)
    users.migrate_family_roles(db)
    users.validate_schema(db)
    users.bootstrap_owner_from_environment(db)
    organizations.validate_schema(db)
    playbooks.validate_schema(db)
    lead_research.migrate(db)
    lead_research.validate_schema(db)
    relationship_manager.migrate(db)
    relationship_manager.validate_schema(db)
    leads.migrate_organization(db)
    leads.validate_schema(db, require_organization=True)
    lead_activities.validate_schema(db)

    # Safe additive migrations for already-live SQLite databases.
    quests.migrate_game_state(db)
    goals.migrate(db)
    quests.migrate_quest_tables(db)
    checkins.migrate(db)
    memory.migrate(db)
    family_ownership.migrate(db)
    family_ownership.create_indexes(db)

    # Ordinary indexes must be created only after legacy columns exist.
    db.executescript(INDEX_SQL)

    quests.create_unique_indexes(db)
    chat.create_unique_indexes(db)
    agent_audit.create_unique_indexes(db)
    leads.create_unique_indexes(db)

    chat.validate_indexes(db)
    agent_audit.validate_indexes(db)
    leads.validate_indexes(db)
    lead_research.validate_indexes(db)
    relationship_manager.validate_indexes(db)
    playbooks.validate_indexes(db)
    users.validate_indexes(db)
    lead_activities.validate_indexes(db)

    quests.backfill(db)
    goals.seed(db)
    quests.seed(db)
    memory.seed(db)
    family_ownership.backfill_owner(db)
    family_workspace.migrate(db)
    family_workspace.ensure_all_workspaces(db)
    family_ownership.validate(db)
    family_workspace.validate(db)
    family_integrity.create_triggers(db)
    family_integrity.validate_triggers(db)
