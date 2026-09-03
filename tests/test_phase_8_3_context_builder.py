from __future__ import annotations

import pytest

from app import database
from app.services.chat import create_chat_session, save_chat_message
from app.services.context_builder import (
    MAX_CONTEXT_CHARACTERS,
    build_context,
    estimate_tokens,
)
from app.services.memory import create_memory
from app.services.team_users import create_member


@pytest.fixture
def context_database(tmp_path, monkeypatch):
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "phase-8-3.db")
    database.init_db()
    with database.get_db() as db:
        owner_id = int(
            db.execute("SELECT id FROM users WHERE role = 'owner'").fetchone()[0]
        )
        member = create_member(
            db,
            username="member",
            display_name="Member",
            password="member-password-123",
            password_confirmation="member-password-123",
        )
    return owner_id, int(member["id"])


def _seed_goal(db, *, user_id, title, priority=5):
    db.execute(
        """
        INSERT INTO goals (user_id, title, category, status, priority)
        VALUES (?, ?, 'career', 'active', ?)
        """,
        (user_id, title, priority),
    )


def _seed_quest(db, *, user_id, title, priority=5, status="active"):
    db.execute(
        """
        INSERT INTO tasks (user_id, title, description, status, priority)
        VALUES (?, ?, '', ?, ?)
        """,
        (user_id, title, status, priority),
    )


def _seed_checkin(db, *, user_id, cash=1000, notes="Solid day"):
    db.execute(
        """
        INSERT INTO checkins (
            user_id, cash, expenses, free_hours, energy,
            accomplished, blocker, notes
        )
        VALUES (?, ?, 50, 2, 4, 'Shipped a feature', 'None', ?)
        """,
        (user_id, cash, notes),
    )


def _update_profile(db, *, user_id, name):
    db.execute(
        """
        UPDATE profile
        SET name = ?, wealth_goal = 'Financial independence', weekday_hours = '4 hours',
            weekend_rule = 'rest', strongest_skills = 'coding', primary_blocker = 'time'
        WHERE user_id = ?
        """,
        (name, user_id),
    )


def test_empty_state_returns_safe_defaults(context_database):
    _owner_id, member_id = context_database
    with database.get_db() as db:
        packet = build_context(db, new_message="What should I focus on today?", user_id=member_id)

    assert packet.new_message == "What should I focus on today?"
    assert packet.profile_summary == {
        "name": "Member",
        "wealth_goal": "",
        "weekday_hours": "",
        "weekend_rule": "",
        "strongest_skills": "",
        "primary_blocker": "",
    }
    assert packet.level_progress["level"] == 1
    assert packet.latest_checkin is None
    assert packet.goals == []
    assert packet.quests == []
    assert packet.memories == []
    assert packet.messages == []
    assert packet.crm_record is None
    assert packet.truncated is False
    assert packet.estimated_tokens > 0
    assert packet.system_identity.startswith("You are the MARK-OS assistant")


def test_hidden_xp_threshold_never_enters_context(context_database):
    owner_id, _member_id = context_database
    with database.get_db() as db:
        db.execute(
            """
            UPDATE game_state
            SET level = 4, xp_total = 350, character_class = 'Data Builder'
            WHERE user_id = ?
            """,
            (owner_id,),
        )
        packet = build_context(db, new_message="What level am I?", user_id=owner_id)

    assert packet.level_progress.keys() == {
        "level",
        "xp_total",
        "xp_into_level",
        "character_class",
    }
    assert packet.level_progress["level"] == 4
    assert packet.level_progress["xp_total"] == 350


def test_only_normal_sensitivity_memories_are_included(context_database):
    _owner_id, member_id = context_database
    with database.get_db() as db:
        create_memory(
            db,
            memory_type="preference",
            memory_key="work_hours",
            memory_value="Deep work before lunch.",
            sensitivity="normal",
            user_id=member_id,
        )
        create_memory(
            db,
            memory_type="preference",
            memory_key="salary_notes",
            memory_value="Target rate details.",
            sensitivity="private",
            user_id=member_id,
        )
        create_memory(
            db,
            memory_type="preference",
            memory_key="banking_context",
            memory_value="Account setup notes.",
            sensitivity="restricted",
            user_id=member_id,
        )
        packet = build_context(db, new_message="Any preferences?", user_id=member_id)

    memory_keys = {memory["memory_key"] for memory in packet.memories}
    assert memory_keys == {"work_hours"}


def test_memory_relevance_outranks_raw_importance(context_database):
    owner_id, _member_id = context_database
    with database.get_db() as db:
        create_memory(
            db,
            memory_type="preference",
            memory_key="focus_time",
            memory_value="Prefers deep work sessions before lunch each day.",
            importance=9,
            sensitivity="normal",
            user_id=owner_id,
        )
        create_memory(
            db,
            memory_type="lesson",
            memory_key="release_process",
            memory_value="Deployment notes: always tag a release before deploying.",
            importance=2,
            sensitivity="normal",
            user_id=owner_id,
        )
        packet = build_context(
            db,
            new_message="What are my deployment notes?",
            user_id=owner_id,
            max_memories=1,
        )

    assert len(packet.memories) == 1
    assert packet.memories[0]["memory_key"] == "release_process"


def test_goals_and_quests_are_scoped_and_bounded(context_database):
    owner_id, member_id = context_database
    with database.get_db() as db:
        # owner_id already owns default-seeded goals/quests from onboarding;
        # they must never leak into the member's own bounded context.
        for index in range(5):
            _seed_goal(db, user_id=member_id, title=f"Member goal {index}", priority=index)
            _seed_quest(db, user_id=member_id, title=f"Member quest {index}", priority=index)

        packet = build_context(
            db,
            new_message="What's next?",
            user_id=member_id,
            max_goals=2,
            max_quests=2,
        )

    assert len(packet.goals) == 2
    assert len(packet.quests) == 2
    assert all("Member" in goal["title"] for goal in packet.goals)
    assert all("Member" in quest["title"] for quest in packet.quests)
    assert packet.goals[0]["priority"] == 4
    assert packet.quests[0]["priority"] == 4


def test_checkin_excludes_financial_figures(context_database):
    owner_id, _member_id = context_database
    with database.get_db() as db:
        _seed_checkin(db, user_id=owner_id)
        packet = build_context(db, new_message="How was my day?", user_id=owner_id)

    assert packet.latest_checkin is not None
    assert "cash" not in packet.latest_checkin
    assert "expenses" not in packet.latest_checkin
    assert "free_hours" not in packet.latest_checkin
    assert packet.latest_checkin["notes"] == "Solid day"


def test_profile_and_level_progress_are_scoped_per_user(context_database):
    owner_id, member_id = context_database
    with database.get_db() as db:
        _update_profile(db, user_id=owner_id, name="Mark")
        _update_profile(db, user_id=member_id, name="Family Member")
        db.execute(
            """
            UPDATE game_state
            SET level = 7, xp_total = 900, character_class = 'Business Owner'
            WHERE user_id = ?
            """,
            (owner_id,),
        )

        owner_packet = build_context(db, new_message="Status?", user_id=owner_id)
        member_packet = build_context(db, new_message="Status?", user_id=member_id)

    assert owner_packet.profile_summary["name"] == "Mark"
    assert owner_packet.level_progress["level"] == 7
    assert member_packet.profile_summary["name"] == "Family Member"
    assert member_packet.level_progress["level"] == 1


def test_recent_messages_are_bounded_and_chronological(context_database):
    owner_id, _member_id = context_database
    with database.get_db() as db:
        session = create_chat_session(db, user_id=owner_id)
        for number in range(15):
            save_chat_message(
                db,
                session_id=session["id"],
                role="user",
                content=f"message {number}",
                user_id=owner_id,
            )
        packet = build_context(
            db,
            new_message="Recap please",
            user_id=owner_id,
            session_id=session["id"],
        )

    assert len(packet.messages) == 10
    assert packet.messages[0]["content"] == "message 5"
    assert packet.messages[-1]["content"] == "message 14"


def test_crm_record_is_caller_supplied_and_passed_through(context_database):
    owner_id, _member_id = context_database
    crm_record = {"lead_id": 42, "company": "Acme", "pipeline_status": "proposal"}
    with database.get_db() as db:
        packet = build_context(
            db,
            new_message="Update me on Acme.",
            user_id=owner_id,
            crm_record=crm_record,
        )

    assert packet.crm_record == crm_record
    assert packet.to_provider_payload()["crm_record"] == crm_record


def test_new_message_validation_rejects_blank_and_oversized(context_database):
    owner_id, _member_id = context_database
    with database.get_db() as db:
        with pytest.raises(ValueError):
            build_context(db, new_message="   ", user_id=owner_id)
        with pytest.raises(ValueError):
            build_context(db, new_message="x" * 4_001, user_id=owner_id)


def test_large_memory_set_is_trimmed_to_hard_budget(context_database):
    owner_id, _member_id = context_database
    with database.get_db() as db:
        for index in range(10):
            create_memory(
                db,
                memory_type="lesson",
                memory_key=f"lesson_{index}",
                memory_value="x" * 900,
                importance=5,
                sensitivity="normal",
                user_id=owner_id,
            )
        packet = build_context(
            db,
            new_message="Summarize my lessons",
            user_id=owner_id,
            max_memories=10,
        )

    assert packet.truncated is True
    assert len(packet.memories) < 10
    payload_size = len(str(packet.to_provider_payload()))
    assert payload_size <= MAX_CONTEXT_CHARACTERS + 500


def test_estimate_tokens_is_roughly_four_chars_per_token():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 40) == 10
