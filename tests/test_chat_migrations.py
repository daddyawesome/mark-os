import sqlite3

import pytest

from app import database


PROTECTED_PHASE4_TABLES = (
    "tasks",
    "quest_updates",
    "xp_ledger",
    "game_state",
    "game_history",
    "checkins",
    "directions",
    "memories",
    "timeline_events",
)


def _table_names(db: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _index_names(db: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }


def _snapshot(db: sqlite3.Connection, table_name: str) -> list[tuple]:
    return [
        tuple(row)
        for row in db.execute(f"SELECT * FROM {table_name} ORDER BY id").fetchall()
    ]


def _create_pre_chat_phase4_database(database_path) -> None:
    db = sqlite3.connect(database_path)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            priority INTEGER NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            purpose TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            priority INTEGER NOT NULL DEFAULT 5,
            progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
            next_action TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            goal_id INTEGER REFERENCES goals(id)
        );

        CREATE TABLE checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checkin_date TEXT NOT NULL DEFAULT (date('now', 'localtime')),
            cash REAL,
            expenses REAL NOT NULL DEFAULT 0,
            free_hours REAL NOT NULL DEFAULT 0,
            energy INTEGER NOT NULL DEFAULT 3 CHECK(energy BETWEEN 1 AND 5),
            accomplished TEXT NOT NULL DEFAULT '',
            blocker TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            cash_in REAL,
            updated_at TEXT
        );

        CREATE TABLE directions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checkin_id INTEGER NOT NULL,
            main_quest TEXT NOT NULL,
            why TEXT NOT NULL,
            side_quest_1 TEXT NOT NULL,
            side_quest_2 TEXT NOT NULL,
            avoid TEXT NOT NULL,
            signal TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (checkin_id) REFERENCES checkins(id) ON DELETE CASCADE
        );

        CREATE TABLE game_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            level INTEGER NOT NULL DEFAULT 1 CHECK(level >= 1),
            xp_total INTEGER,
            character_class TEXT NOT NULL,
            threshold_mode TEXT NOT NULL DEFAULT 'hidden',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source TEXT NOT NULL DEFAULT 'system',
            notes TEXT NOT NULL DEFAULT '',
            xp_into_level INTEGER NOT NULL DEFAULT 0,
            last_level_up_at TEXT
        );

        CREATE TABLE game_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            level INTEGER NOT NULL CHECK(level >= 1),
            xp_total INTEGER,
            event TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            memory_key TEXT NOT NULL UNIQUE,
            memory_value TEXT NOT NULL,
            importance INTEGER NOT NULL DEFAULT 5 CHECK(importance BETWEEN 1 AND 10),
            source TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE timeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'completed',
            importance INTEGER NOT NULL DEFAULT 5 CHECK(importance BETWEEN 1 AND 10),
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            goal_id INTEGER,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'backlog',
            priority INTEGER NOT NULL DEFAULT 5,
            estimated_minutes INTEGER,
            actual_minutes INTEGER NOT NULL DEFAULT 0,
            energy_required INTEGER NOT NULL DEFAULT 3 CHECK(energy_required BETWEEN 1 AND 5),
            due_date TEXT,
            difficulty TEXT NOT NULL DEFAULT 'normal',
            xp_reward INTEGER NOT NULL DEFAULT 25,
            progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
            quest_source TEXT NOT NULL DEFAULT 'manual',
            why TEXT NOT NULL DEFAULT '',
            blocked_reason TEXT NOT NULL DEFAULT '',
            result_notes TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '',
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
            FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE SET NULL
        );

        CREATE TABLE quest_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            progress INTEGER,
            actual_minutes INTEGER,
            session_minutes INTEGER,
            blocker_reason TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL DEFAULT 'update',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );

        CREATE TABLE xp_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL UNIQUE,
            event_key TEXT,
            event_type TEXT NOT NULL DEFAULT 'quest_completed',
            source_type TEXT NOT NULL DEFAULT 'quest',
            source_id INTEGER,
            source_title TEXT NOT NULL DEFAULT '',
            xp_delta INTEGER NOT NULL,
            level_before INTEGER NOT NULL,
            level_after INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
        """
    )

    db.execute(
        """
        INSERT INTO goals (id, title, category, status, priority, created_at)
        VALUES (90, 'Legacy goal', 'test', 'active', 7, '2026-01-01 09:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO projects
            (id, name, purpose, status, priority, progress, next_action,
             created_at, updated_at, goal_id)
        VALUES
            (90, 'Legacy project', 'Preserve data', 'active', 7, 40,
             'Keep migrating', '2026-01-01 09:00:00', '2026-01-02 09:00:00', 90)
        """
    )
    db.execute(
        """
        INSERT INTO checkins
            (id, checkin_date, cash, expenses, free_hours, energy, accomplished,
             blocker, notes, created_at, cash_in, updated_at)
        VALUES
            (90, '2026-01-02', 1080, 20, 2.5, 4, 'Shipped Phase 4',
             '', 'Legacy check-in', '2026-01-02 09:00:00', 100,
             '2026-01-02 09:30:00')
        """
    )
    db.execute(
        """
        INSERT INTO directions
            (id, checkin_id, main_quest, why, side_quest_1, side_quest_2,
             avoid, signal, created_at)
        VALUES
            (90, 90, 'Preserve data', 'Safety', 'Test fresh', 'Test legacy',
             'Destructive migration', 'migration-safe', '2026-01-02 09:31:00')
        """
    )
    db.execute(
        """
        INSERT INTO game_state
            (id, level, xp_total, character_class, threshold_mode, updated_at,
             source, notes, xp_into_level, last_level_up_at)
        VALUES
            (1, 3, 250, 'Legacy Builder', 'hidden', '2026-01-02 10:00:00',
             'import', 'Keep Level 3', 25, '2026-01-01 10:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO game_history
            (id, event_date, level, xp_total, event, source, created_at)
        VALUES
            (90, '2026-01-01', 3, 250, 'Reached Level 3', 'import',
             '2026-01-01 10:00:00')
        """
    )
    db.executemany(
        """
        INSERT INTO memories
            (id, memory_type, memory_key, memory_value, importance, source,
             active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                1,
                "product_principle",
                "phase_4_revised_dod",
                "Existing Phase 4 definition",
                9,
                "phase_4_revised",
                1,
                "2026-01-01 08:00:00",
                "2026-01-01 08:00:00",
            ),
            (
                90,
                "lesson",
                "legacy-memory",
                "Never lose existing memories",
                10,
                "test",
                1,
                "2026-01-02 08:00:00",
                "2026-01-02 08:00:00",
            ),
        ),
    )
    db.execute(
        """
        INSERT INTO tasks
            (id, project_id, goal_id, title, description, status, priority,
             estimated_minutes, actual_minutes, energy_required, due_date,
             difficulty, xp_reward, progress, quest_source, why, blocked_reason,
             result_notes, evidence, started_at, completed_at, created_at, updated_at)
        VALUES
            (90, 90, 90, 'Legacy completed quest', 'Keep this quest', 'completed',
             8, 60, 55, 3, '2026-01-02', 'hard', 50, 100, 'manual',
             'Regression proof', '', 'Completed safely', 'commit legacy',
             '2026-01-02 10:00:00', '2026-01-02 11:00:00',
             '2026-01-01 10:00:00', '2026-01-02 11:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO quest_updates
            (id, task_id, note, progress, actual_minutes, session_minutes,
             blocker_reason, event_type, created_at)
        VALUES
            (90, 90, 'Finished', 100, 55, 55, '', 'completed',
             '2026-01-02 11:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO xp_ledger
            (id, task_id, event_key, event_type, source_type, source_id,
             source_title, xp_delta, level_before, level_after, reason, created_at)
        VALUES
            (90, 90, 'quest_completed:90', 'quest_completed', 'quest', 90,
             'Legacy completed quest', 50, 2, 3,
             'Completed quest: Legacy completed quest', '2026-01-02 11:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO timeline_events
            (id, event_date, event_type, title, summary, details_json, status,
             importance, source, created_at)
        VALUES
            (90, '2026-01-02', 'quest_completed', 'Legacy completed quest',
             'Completed safely', '{}', 'completed', 8, 'quest_engine',
             '2026-01-02 11:00:00')
        """
    )
    db.commit()
    db.close()


def test_fresh_database_has_chat_schema_indexes_and_foreign_key(tmp_path, monkeypatch):
    database_path = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)

    database.init_db()
    database.init_db()

    db = sqlite3.connect(database_path)
    assert {"chat_sessions", "chat_messages"}.issubset(_table_names(db))
    assert {
        "idx_chat_sessions_status_activity",
        "idx_chat_messages_recent",
        "idx_chat_messages_request_key",
    }.issubset(_index_names(db))

    session_columns = {
        row[1] for row in db.execute("PRAGMA table_info(chat_sessions)").fetchall()
    }
    message_columns = {
        row[1] for row in db.execute("PRAGMA table_info(chat_messages)").fetchall()
    }
    assert {
        "id",
        "title",
        "status",
        "created_at",
        "updated_at",
        "last_message_at",
        "archived_at",
    } == session_columns
    assert {
        "id",
        "session_id",
        "role",
        "content",
        "request_key",
        "edited_at",
        "deleted_at",
        "created_at",
        "updated_at",
    } == message_columns

    foreign_keys = db.execute("PRAGMA foreign_key_list(chat_messages)").fetchall()
    assert any(row[2] == "chat_sessions" and row[6] == "CASCADE" for row in foreign_keys)
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO chat_sessions (title, status) VALUES ('Bad', 'unknown')"
        )
    session_id = db.execute(
        "INSERT INTO chat_sessions (title, status) VALUES ('Valid', 'active')"
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO chat_messages (session_id, role, content)
            VALUES (?, 'invalid-role', 'Bad role')
            """,
            (session_id,),
        )
    db.close()


def test_pre_chat_phase4_database_upgrades_without_data_loss(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    _create_pre_chat_phase4_database(database_path)
    monkeypatch.setattr(database, "DB_PATH", database_path)

    before_db = sqlite3.connect(database_path)
    before = {
        table: _snapshot(before_db, table) for table in PROTECTED_PHASE4_TABLES
    }
    before_db.close()

    database.init_db()
    database.init_db()

    after_db = sqlite3.connect(database_path)
    after = {
        table: _snapshot(after_db, table) for table in PROTECTED_PHASE4_TABLES
    }
    assert before == after
    assert {"chat_sessions", "chat_messages"}.issubset(_table_names(after_db))
    assert after_db.execute("SELECT level FROM game_state WHERE id = 1").fetchone()[0] == 3
    assert after_db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    assert after_db.execute("SELECT COUNT(*) FROM xp_ledger").fetchone()[0] == 1
    assert after_db.execute("SELECT COUNT(*) FROM checkins").fetchone()[0] == 1
    assert after_db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 2
    assert after_db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert after_db.execute("PRAGMA foreign_key_check").fetchall() == []
    after_db.close()


def test_older_tasks_schema_migrates_columns_before_dependent_indexes(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "older-tasks.db"
    db = sqlite3.connect(database_path)
    db.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'backlog',
            priority INTEGER NOT NULL DEFAULT 5,
            estimated_minutes INTEGER,
            due_date TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );
        INSERT INTO tasks
            (id, title, description, status, priority, estimated_minutes,
             due_date, created_at)
        VALUES
            (77, 'Older quest', 'Must survive migration', 'active', 9, 30,
             '2026-02-01', '2026-01-31 08:00:00');
        """
    )
    db.commit()
    db.close()
    monkeypatch.setattr(database, "DB_PATH", database_path)

    database.init_db()

    db = sqlite3.connect(database_path)
    task_columns = {
        row[1] for row in db.execute("PRAGMA table_info(tasks)").fetchall()
    }
    quest = db.execute(
        "SELECT title, description, status, priority, updated_at FROM tasks WHERE id = 77"
    ).fetchone()
    assert {"goal_id", "updated_at", "xp_reward", "actual_minutes"}.issubset(
        task_columns
    )
    assert quest == (
        "Older quest",
        "Must survive migration",
        "active",
        9,
        "2026-01-31 08:00:00",
    )
    assert "idx_tasks_goal" in _index_names(db)
    assert {"chat_sessions", "chat_messages"}.issubset(_table_names(db))
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


def test_incompatible_partial_chat_schema_fails_without_silent_weakening(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "partial-chat.db"
    db = sqlite3.connect(database_path)
    db.executescript(
        """
        CREATE TABLE chat_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT);
        CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT);
        INSERT INTO chat_sessions DEFAULT VALUES;
        """
    )
    db.commit()
    db.close()
    monkeypatch.setattr(database, "DB_PATH", database_path)

    with pytest.raises(RuntimeError, match="Incompatible chat_sessions schema"):
        database.init_db()

    db = sqlite3.connect(database_path)
    session = db.execute("SELECT * FROM chat_sessions WHERE id = 1").fetchone()
    assert session is not None
    assert "idx_chat_messages_request_key" not in _index_names(db)
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


def test_chat_schema_without_integer_primary_key_fails_validation(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "missing-chat-primary-key.db"
    db = sqlite3.connect(database_path)
    db.executescript(
        """
        CREATE TABLE chat_sessions (
            id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT 'New chat',
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'archived')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_message_at TEXT,
            archived_at TEXT
        );
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL
                CHECK(role IN ('user', 'assistant', 'system', 'tool')),
            content TEXT NOT NULL,
            request_key TEXT,
            edited_at TEXT,
            deleted_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        );
        """
    )
    db.close()
    monkeypatch.setattr(database, "DB_PATH", database_path)

    with pytest.raises(RuntimeError, match="id must be INTEGER PRIMARY KEY"):
        database.init_db()


def test_orphaned_existing_chat_message_fails_validation_without_data_loss(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "orphan-chat-message.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = sqlite3.connect(database_path)
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute(
        """
        INSERT INTO chat_messages (session_id, role, content, request_key)
        VALUES (9999, 'user', 'Orphaned but preserved', 'orphan-request')
        """
    )
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="orphaned session references"):
        database.init_db()

    db = sqlite3.connect(database_path)
    assert db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 1
    db.close()


def test_narrowed_request_key_index_predicate_fails_validation(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "narrow-request-index.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = sqlite3.connect(database_path)
    db.execute("DROP INDEX idx_chat_messages_request_key")
    db.execute(
        """
        CREATE UNIQUE INDEX idx_chat_messages_request_key
        ON chat_messages(session_id, request_key)
        WHERE request_key IS NOT NULL AND role = 'user'
        """
    )
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="wrong predicate"):
        database.init_db()


def test_existing_duplicate_request_keys_fail_with_clear_migration_error(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "duplicate-keys.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    db = sqlite3.connect(database_path)
    db.execute("DROP INDEX idx_chat_messages_request_key")
    session_id = db.execute(
        "INSERT INTO chat_sessions (title, status) VALUES ('Legacy chat', 'active')"
    ).lastrowid
    db.executemany(
        """
        INSERT INTO chat_messages (session_id, role, content, request_key)
        VALUES (?, 'user', ?, 'duplicate-key')
        """,
        (
            (session_id, "First copy"),
            (session_id, "Second copy"),
        ),
    )
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="duplicate request keys"):
        database.init_db()

    db = sqlite3.connect(database_path)
    assert db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 2
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()


def test_application_startup_initializes_chat_on_temporary_database(
    tmp_path,
    monkeypatch,
):
    from app.main import startup

    database_path = tmp_path / "startup.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)

    startup()
    startup()

    db = sqlite3.connect(database_path)
    assert {"chat_sessions", "chat_messages"}.issubset(_table_names(db))
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.close()
