import sqlite3

import pytest

from app import database
from app.services.chat import (
    archive_chat_session,
    create_chat_session,
    delete_chat_message,
    delete_or_soft_delete_chat_message,
    delete_chat_session,
    delete_or_archive_chat_session,
    edit_chat_message,
    get_chat_session,
    get_recent_chat_messages,
    list_chat_sessions,
    rename_chat_session,
    save_chat_message,
)


@pytest.fixture
def chat_database(tmp_path, monkeypatch):
    database_path = tmp_path / "chat.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()
    return database_path


def test_session_create_read_list_rename_and_archive(chat_database):
    with database.get_db() as db:
        first = create_chat_session(db, title="  Phase 5 planning  ")
        second = create_chat_session(db)

        assert first["title"] == "Phase 5 planning"
        assert second["title"] == "New chat"
        assert get_chat_session(db, first["id"])["status"] == "active"
        assert {row["id"] for row in list_chat_sessions(db)} == {
            first["id"],
            second["id"],
        }

        renamed = rename_chat_session(db, first["id"], title="Persistent chat")
        assert renamed["title"] == "Persistent chat"

        archived = archive_chat_session(db, first["id"])
        assert archived["status"] == "archived"
        assert archived["archived_at"] is not None
        assert [row["id"] for row in list_chat_sessions(db)] == [second["id"]]
        assert {row["id"] for row in list_chat_sessions(db, include_archived=True)} == {
            first["id"],
            second["id"],
        }

        with pytest.raises(ValueError, match="archived"):
            save_chat_message(
                db,
                session_id=first["id"],
                role="user",
                content="This should not be added.",
            )


def test_messages_persist_and_recent_history_is_chronological(chat_database):
    with database.get_db() as db:
        session = create_chat_session(db, title="Persistence")
        session_id = session["id"]
        for number in range(12):
            save_chat_message(
                db,
                session_id=session_id,
                role="user" if number % 2 == 0 else "assistant",
                content=f"message {number}",
                request_key=f"request-{number}",
            )

    # A new connection represents a later request or process restart.
    with database.get_db() as db:
        history = get_recent_chat_messages(db, session_id)
        assert [row["content"] for row in history] == [
            f"message {number}" for number in range(2, 12)
        ]
        assert [row["id"] for row in history] == sorted(row["id"] for row in history)

        shorter_history = get_recent_chat_messages(db, session_id, limit=3)
        assert [row["content"] for row in shorter_history] == [
            "message 9",
            "message 10",
            "message 11",
        ]


def test_request_key_prevents_retries_but_not_legitimate_repeated_content(chat_database):
    with database.get_db() as db:
        session = create_chat_session(db)
        first = save_chat_message(
            db,
            session_id=session["id"],
            role="user",
            content="Run the migration checks",
            request_key="submission-123",
        )
        retry = save_chat_message(
            db,
            session_id=session["id"],
            role="USER",
            content="Run the migration checks",
            request_key=" submission-123 ",
        )
        legitimate_repeat = save_chat_message(
            db,
            session_id=session["id"],
            role="user",
            content="Run the migration checks",
            request_key="submission-124",
        )

        assert first.created is True
        assert retry.duplicate is True
        assert retry.message["id"] == first.message["id"]
        assert legitimate_repeat.created is True
        assert legitimate_repeat.message["id"] != first.message["id"]

        with pytest.raises(ValueError, match="different chat message"):
            save_chat_message(
                db,
                session_id=session["id"],
                role="user",
                content="Different payload",
                request_key="submission-123",
            )

        count = db.execute(
            "SELECT COUNT(*) AS count FROM chat_messages WHERE session_id = ?",
            (session["id"],),
        ).fetchone()["count"]
        assert count == 2


def test_duplicate_scope_and_unkeyed_repeated_messages(chat_database):
    with database.get_db() as db:
        first_session = create_chat_session(db)
        second_session = create_chat_session(db)

        first = save_chat_message(
            db,
            session_id=first_session["id"],
            role="user",
            content="Same words",
            request_key="same-key",
        )
        second = save_chat_message(
            db,
            session_id=second_session["id"],
            role="user",
            content="Same words",
            request_key="same-key",
        )
        unkeyed_one = save_chat_message(
            db,
            session_id=first_session["id"],
            role="user",
            content="Repeated without a key",
        )
        unkeyed_two = save_chat_message(
            db,
            session_id=first_session["id"],
            role="user",
            content="Repeated without a key",
        )

        assert first.created and second.created
        assert first.message["id"] != second.message["id"]
        assert unkeyed_one.message["id"] != unkeyed_two.message["id"]


def test_message_content_preserves_markdown_and_code_whitespace(chat_database):
    with database.get_db() as db:
        session = create_chat_session(db)
        original = "\n```python\n    print('preserved')\n```\n"
        saved = save_chat_message(
            db,
            session_id=session["id"],
            role="user",
            content=original,
        ).message
        assert saved["content"] == original

        edited_content = "\n    indented follow-up\n"
        edited = edit_chat_message(db, saved["id"], content=edited_content)
        assert edited["content"] == edited_content


def test_edit_and_confirmed_message_deletion_are_safe(chat_database):
    with database.get_db() as db:
        session = create_chat_session(db)
        first = save_chat_message(
            db,
            session_id=session["id"],
            role="user",
            content="Mispelled message",
        ).message
        second = save_chat_message(
            db,
            session_id=session["id"],
            role="assistant",
            content="A response",
        ).message

        edited = edit_chat_message(db, first["id"], content="Misspelled message")
        assert edited["content"] == "Misspelled message"
        assert edited["edited_at"] is not None

        with pytest.raises(ValueError, match="requires confirmation"):
            delete_chat_message(db, first["id"])
        with pytest.raises(ValueError, match="requires confirmation"):
            delete_chat_message(db, first["id"], confirmed="true")

        assert delete_or_soft_delete_chat_message(
            db,
            first["id"],
            confirmed=True,
            hard_delete="false",
        ) is True
        remaining = get_recent_chat_messages(db, session["id"])
        assert [row["id"] for row in remaining] == [second["id"]]
        deleted = db.execute(
            "SELECT * FROM chat_messages WHERE id = ?",
            (first["id"],),
        ).fetchone()
        assert deleted["deleted_at"] is not None

        with pytest.raises(ValueError, match="cannot be edited"):
            edit_chat_message(db, first["id"], content="Try again")

        assert delete_chat_message(
            db,
            second["id"],
            confirmed=True,
            hard_delete=True,
        ) is True
        assert db.execute(
            "SELECT 1 FROM chat_messages WHERE id = ?",
            (second["id"],),
        ).fetchone() is None
        assert get_chat_session(db, session["id"])["last_message_at"] is None


def test_session_archive_and_confirmed_delete_cascades_messages(chat_database):
    with database.get_db() as db:
        session = create_chat_session(db, title="Disposable")
        message = save_chat_message(
            db,
            session_id=session["id"],
            role="user",
            content="Delete with the session",
        ).message

        archived = delete_or_archive_chat_session(
            db,
            session["id"],
            hard_delete="false",
            confirmed="true",
        )
        assert archived["status"] == "archived"
        assert db.execute(
            "SELECT 1 FROM chat_messages WHERE id = ?",
            (message["id"],),
        ).fetchone() is not None

        with pytest.raises(ValueError, match="requires confirmation"):
            delete_chat_session(db, session["id"])
        with pytest.raises(ValueError, match="requires confirmation"):
            delete_chat_session(db, session["id"], confirmed="true")

        assert delete_chat_session(db, session["id"], confirmed=True) is True
        assert get_chat_session(db, session["id"]) is None
        assert db.execute(
            "SELECT 1 FROM chat_messages WHERE id = ?",
            (message["id"],),
        ).fetchone() is None


def test_chat_message_foreign_key_is_enforced(chat_database):
    with database.get_db() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """
                INSERT INTO chat_messages (session_id, role, content)
                VALUES (?, 'user', 'orphan')
                """,
                (999_999,),
            )


def test_idempotency_constraint_race_returns_existing_message(chat_database):
    class InsertRaceConnection:
        def __init__(self, connection):
            self.connection = connection
            self.inserted_competing_row = False

        def execute(self, sql, parameters=()):
            normalized_sql = " ".join(sql.split()).upper()
            if (
                not self.inserted_competing_row
                and normalized_sql.startswith("INSERT INTO CHAT_MESSAGES")
            ):
                self.connection.execute(sql, parameters)
                self.inserted_competing_row = True
            return self.connection.execute(sql, parameters)

    with database.get_db() as db:
        session = create_chat_session(db)
        racing_db = InsertRaceConnection(db)
        saved = save_chat_message(
            racing_db,
            session_id=session["id"],
            role="user",
            content="One submission",
            request_key="racing-request",
        )

        assert saved.duplicate is True
        assert saved.message["request_key"] == "racing-request"
        assert db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 1


def test_chat_writes_roll_back_with_the_outer_transaction(chat_database):
    with pytest.raises(RuntimeError, match="force rollback"):
        with database.get_db() as db:
            session = create_chat_session(db, title="Rolled back")
            save_chat_message(
                db,
                session_id=session["id"],
                role="user",
                content="This must roll back",
            )
            raise RuntimeError("force rollback")

    with database.get_db() as db:
        assert db.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
