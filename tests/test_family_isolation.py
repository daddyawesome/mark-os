from __future__ import annotations

import sqlite3

import pytest

from app import database
from app.routes.shared import (
    load_open_quests,
    load_system_state,
)
from app.services.chat import (
    create_chat_session,
    get_chat_session,
    list_chat_sessions,
    save_chat_message,
)
from app.services.leads import create_lead
from app.services.personal_scope import user_scope
from app.services.quests import set_quest_status
from app.services.team_users import (
    create_lead_sourcer,
    create_member,
    get_primary_owner_id,
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv(
        "MARK_OS_PASSWORD",
        "owner-password-123",
    )
    monkeypatch.setenv(
        "MARK_OS_DISPLAY_NAME",
        "Mark",
    )


def _create_family(db):
    wife = create_member(
        db,
        username="wife",
        display_name="Wife",
        password="family-pass-123",
        password_confirmation="family-pass-123",
    )
    child = create_member(
        db,
        username="child",
        display_name="Child",
        password="family-pass-456",
        password_confirmation="family-pass-456",
    )
    return wife, child


def _insert_task(
    db,
    *,
    user_id: int,
    title: str,
) -> int:
    return int(
        db.execute(
            """
            INSERT INTO tasks (
                user_id,
                title,
                description,
                status,
                quest_source,
                why
            )
            VALUES (?, ?, '', 'backlog', 'manual', '')
            """,
            (user_id, title),
        ).lastrowid
    )


def test_dashboard_helpers_return_only_current_users_data(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "scoped-dashboard.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(
            db,
            active_only=True,
        )
        wife, _ = _create_family(db)
        owner_task = _insert_task(
            db,
            user_id=owner_id,
            title="Owner private quest",
        )
        wife_task = _insert_task(
            db,
            user_id=wife["id"],
            title="Wife private quest",
        )

        owner_rows = load_open_quests(db, owner_id)
        wife_rows = load_open_quests(db, wife["id"])
        owner_state = load_system_state(db, owner_id)
        wife_state = load_system_state(db, wife["id"])

    assert {row["id"] for row in owner_rows} >= {owner_task}
    assert wife_task not in {row["id"] for row in owner_rows}
    assert {row["id"] for row in wife_rows} == {wife_task}
    assert owner_state["task_count"] >= 1
    assert wife_state["task_count"] == 1


def test_quest_mutations_cannot_cross_users(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "scoped-quests.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(
            db,
            active_only=True,
        )
        wife, _ = _create_family(db)
        owner_task = _insert_task(
            db,
            user_id=owner_id,
            title="Owner task",
        )
        wife_task = _insert_task(
            db,
            user_id=wife["id"],
            title="Wife task",
        )

        with user_scope(wife["id"]):
            with pytest.raises(
                ValueError,
                match="Quest not found",
            ):
                set_quest_status(
                    db,
                    quest_id=owner_task,
                    status="active",
                )

            set_quest_status(
                db,
                quest_id=wife_task,
                status="active",
            )

        owner_status = db.execute(
            "SELECT status FROM tasks WHERE id = ?",
            (owner_task,),
        ).fetchone()["status"]
        wife_status = db.execute(
            "SELECT status FROM tasks WHERE id = ?",
            (wife_task,),
        ).fetchone()["status"]

    assert owner_status == "backlog"
    assert wife_status == "active"


def test_chat_sessions_and_messages_are_private(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "scoped-chat.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(
            db,
            active_only=True,
        )
        wife, _ = _create_family(db)

        with user_scope(owner_id):
            owner_session = create_chat_session(
                db,
                title="Owner private chat",
            )
            save_chat_message(
                db,
                session_id=owner_session["id"],
                role="user",
                content="Owner-only message",
            )

        with user_scope(wife["id"]):
            assert (
                get_chat_session(
                    db,
                    owner_session["id"],
                )
                is None
            )
            assert list_chat_sessions(db) == []
            with pytest.raises(
                ValueError,
                match="Chat session not found",
            ):
                save_chat_message(
                    db,
                    session_id=owner_session["id"],
                    role="user",
                    content="Cross-user attempt",
                )

            wife_session = create_chat_session(
                db,
                title="Wife private chat",
            )
            save_chat_message(
                db,
                session_id=wife_session["id"],
                role="user",
                content="Wife-only message",
            )
            wife_sessions = list_chat_sessions(db)

    assert [row["id"] for row in wife_sessions] == [
        wife_session["id"]
    ]


def test_integrity_trigger_rejects_mismatched_child_owner(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "ownership-trigger.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(
            db,
            active_only=True,
        )
        wife, _ = _create_family(db)
        owner_task = _insert_task(
            db,
            user_id=owner_id,
            title="Owner trigger task",
        )

        with pytest.raises(
            sqlite3.IntegrityError,
            match="quest update owner",
        ):
            db.execute(
                """
                INSERT INTO quest_updates (
                    user_id,
                    task_id,
                    note,
                    event_type
                )
                VALUES (?, ?, 'wrong owner', 'update')
                """,
                (wife["id"], owner_task),
            )


def test_crm_linked_quest_is_owned_by_owner(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "crm-quest-owner.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(
            db,
            active_only=True,
        )
        sourcer = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="sourcer-pass-123",
            password_confirmation="sourcer-pass-123",
        )

        result = create_lead(
            db,
            company="Family Safe Analytics",
            contact_person="Alex Buyer",
            source="Referral",
            problem_opportunity="Needs reporting help",
            why_mark_fits="Mark builds data systems",
            next_action="Review the lead",
            created_by_user_id=sourcer["id"],
            assigned_to_user_id=owner_id,
        )

        task = db.execute(
            """
            SELECT user_id
            FROM tasks
            WHERE id = ?
            """,
            (result.quest["id"],),
        ).fetchone()
        updates = db.execute(
            """
            SELECT DISTINCT user_id
            FROM quest_updates
            WHERE task_id = ?
            """,
            (result.quest["id"],),
        ).fetchall()

    assert task["user_id"] == owner_id
    assert {row["user_id"] for row in updates} == {
        owner_id
    }
