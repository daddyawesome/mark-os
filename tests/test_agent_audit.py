import sqlite3

import pytest

from app import database
from app.services.agent_audit import (
    AgentRunCreateResult,
    AgentStepAppendResult,
    MAX_USAGE_VALUE,
    append_agent_step,
    create_agent_run,
    finalize_agent_run,
    get_agent_run,
    list_agent_runs,
    list_agent_steps,
    set_agent_run_context,
)
from app.services.chat import (
    archive_chat_session,
    create_chat_session,
    delete_chat_message,
    save_chat_message,
)


@pytest.fixture
def audit_database(tmp_path, monkeypatch):
    database_path = tmp_path / "agent-audit.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()
    return database_path


def _create_chat_input(
    db: sqlite3.Connection,
    *,
    title: str = "Agent audit",
    role: str = "user",
    content: str = "Audit this request",
) -> tuple[sqlite3.Row, sqlite3.Row]:
    session = create_chat_session(db, title=title)
    message = save_chat_message(
        db,
        session_id=session["id"],
        role=role,
        content=content,
    ).message
    return session, message


def _create_run(
    db: sqlite3.Connection,
    session: sqlite3.Row,
    message: sqlite3.Row,
    *,
    request_key: str | None = None,
    intent: str = "chat",
    loop_selected: str = "chat_loop",
) -> AgentRunCreateResult:
    return create_agent_run(
        db,
        session_id=session["id"],
        user_message_id=message["id"],
        request_key=request_key,
        intent=intent,
        loop_selected=loop_selected,
    )


def test_run_lifecycle_context_retrieval_and_listing(audit_database):
    with database.get_db() as db:
        first_session, first_message = _create_chat_input(db, title="First")
        second_session, second_message = _create_chat_input(db, title="Second")

        first = create_agent_run(
            db,
            session_id=first_session["id"],
            user_message_id=first_message["id"],
            request_key="run-first",
        )
        second = _create_run(
            db,
            first_session,
            first_message,
            request_key="run-second",
            intent="quest.create",
            loop_selected="quest_loop",
        )
        other_session = _create_run(
            db,
            second_session,
            second_message,
            request_key="run-other-session",
        )

        assert isinstance(first, AgentRunCreateResult)
        assert first.created is True
        assert first.duplicate is False
        assert first.run["session_id"] == first_session["id"]
        assert first.run["user_message_id"] == first_message["id"]
        assert first.run["intent"] == "unknown"
        assert first.run["loop_selected"] == "none"
        assert first.run["status"] == "running"
        assert first.run["step_count"] == 0
        assert first.run["ai_call_count"] == 0
        assert first.run["tool_call_count"] == 0
        assert first.run["input_tokens"] == 0
        assert first.run["output_tokens"] == 0
        assert first.run["estimated_cost_microusd"] == 0
        assert first.run["started_at"] is not None
        assert first.run["completed_at"] is None

        contextualized = set_agent_run_context(
            db,
            first.run["id"],
            intent="  quest.update  ",
            loop_selected="  quest_progress_loop  ",
            provider="  openai  ",
            model="  test-model  ",
        )
        assert contextualized["intent"] == "quest.update"
        assert contextualized["loop_selected"] == "quest_progress_loop"
        assert contextualized["provider"] == "openai"
        assert contextualized["model"] == "test-model"

        completed = finalize_agent_run(db, second.run["id"], status="completed")
        assert completed["completed_at"] is not None

        assert get_agent_run(db, first.run["id"])["intent"] == "quest.update"
        assert get_agent_run(db, 999_999) is None
        assert [row["id"] for row in list_agent_runs(db, limit=1)] == [
            other_session.run["id"]
        ]
        assert [
            row["id"]
            for row in list_agent_runs(db, session_id=first_session["id"])
        ] == [second.run["id"], first.run["id"]]
        assert [row["id"] for row in list_agent_runs(db, status="completed")] == [
            second.run["id"]
        ]

    with database.get_db() as db:
        persisted = get_agent_run(db, first.run["id"])
        assert persisted["provider"] == "openai"
        assert persisted["model"] == "test-model"


def test_run_request_key_is_idempotent_scoped_and_conflict_safe(audit_database):
    with database.get_db() as db:
        first_session, first_message = _create_chat_input(db, title="First")
        second_session, second_message = _create_chat_input(db, title="Second")

        created = create_agent_run(
            db,
            session_id=first_session["id"],
            user_message_id=first_message["id"],
            request_key=" run-request ",
            intent=" quest.create ",
            loop_selected=" quest_loop ",
            provider=" openai ",
            model=" test-model ",
        )
        retry = create_agent_run(
            db,
            session_id=first_session["id"],
            user_message_id=first_message["id"],
            request_key="run-request",
            intent="quest.create",
            loop_selected="quest_loop",
            provider="openai",
            model="test-model",
        )
        set_agent_run_context(
            db,
            created.run["id"],
            intent="quest.update",
            loop_selected="quest_progress_loop",
            provider="local",
            model="deterministic",
        )
        retry_after_context_change = create_agent_run(
            db,
            session_id=first_session["id"],
            user_message_id=first_message["id"],
            request_key="run-request",
            intent="quest.create",
            loop_selected="quest_loop",
            provider="openai",
            model="test-model",
        )
        same_key_other_session = create_agent_run(
            db,
            session_id=second_session["id"],
            user_message_id=second_message["id"],
            request_key="run-request",
            intent="quest.create",
            loop_selected="quest_loop",
            provider="openai",
            model="test-model",
        )

        assert created.created is True
        assert retry.created is False
        assert retry.duplicate is True
        assert retry.run["id"] == created.run["id"]
        assert retry_after_context_change.duplicate is True
        assert retry_after_context_change.run["id"] == created.run["id"]
        assert retry_after_context_change.run["intent"] == "quest.update"
        assert same_key_other_session.created is True
        assert same_key_other_session.run["id"] != created.run["id"]

        different_message = save_chat_message(
            db,
            session_id=first_session["id"],
            role="user",
            content="A distinct request in the same session",
        ).message
        with pytest.raises(ValueError, match="different agent run"):
            create_agent_run(
                db,
                session_id=first_session["id"],
                user_message_id=different_message["id"],
                request_key="run-request",
                intent="quest.create",
                loop_selected="quest_loop",
                provider="openai",
                model="test-model",
            )

        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 2


def test_run_requires_an_active_session_and_matching_live_user_message(
    audit_database,
):
    with database.get_db() as db:
        first_session, first_message = _create_chat_input(db, title="First")
        second_session, second_message = _create_chat_input(db, title="Second")
        _, assistant_message = _create_chat_input(
            db,
            title="Assistant source",
            role="assistant",
        )
        deleted_session, deleted_message = _create_chat_input(db, title="Deleted")
        archived_session, archived_message = _create_chat_input(db, title="Archived")
        delete_chat_message(db, deleted_message["id"], confirmed=True)
        archive_chat_session(db, archived_session["id"])

        invalid_references = [
            (999_999, first_message["id"]),
            (first_session["id"], 999_999),
            (first_session["id"], second_message["id"]),
            (
                assistant_message["session_id"],
                assistant_message["id"],
            ),
            (deleted_session["id"], deleted_message["id"]),
            (archived_session["id"], archived_message["id"]),
        ]
        for session_id, message_id in invalid_references:
            with pytest.raises(ValueError):
                create_agent_run(
                    db,
                    session_id=session_id,
                    user_message_id=message_id,
                    intent="chat",
                    loop_selected="chat_loop",
                )

        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0
        assert first_session["id"] != second_session["id"]


def test_steps_are_chronological_and_run_usage_is_recomputed(audit_database):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run

        deterministic = append_agent_step(
            db,
            run_id=run["id"],
            step_key="classify",
            step_type="rule",
            name="classify_intent",
        )
        ai_call = append_agent_step(
            db,
            run_id=run["id"],
            step_key="generate",
            step_type="ai_call",
            name="generate_response",
            provider="openai",
            model="test-model",
            input_tokens=120,
            output_tokens=30,
            estimated_cost_microusd=250,
        )

        # Aggregate fields are a cache derived from steps, not values to increment
        # blindly. A later append must repair any stale cached totals.
        db.execute(
            """
            UPDATE agent_runs
            SET step_count = 99,
                ai_call_count = 99,
                tool_call_count = 99,
                input_tokens = 99,
                output_tokens = 99,
                estimated_cost_microusd = 99
            WHERE id = ?
            """,
            (run["id"],),
        )
        tool_call = append_agent_step(
            db,
            run_id=run["id"],
            step_key="quest-tool",
            step_type="tool_call",
            name="create_quest",
            status="failed",
            tool_name="create_quest",
            estimated_cost_microusd=15,
            error_code="tool_validation",
            error_message="Quest title is required",
        )
        skipped_ai_call = append_agent_step(
            db,
            run_id=run["id"],
            step_key="skip-escalation",
            step_type="ai_call",
            name="optional_escalation",
            status="skipped",
            provider="openai",
            model="test-model",
        )

        assert isinstance(deterministic, AgentStepAppendResult)
        assert isinstance(ai_call, AgentStepAppendResult)
        assert isinstance(tool_call, AgentStepAppendResult)
        assert isinstance(skipped_ai_call, AgentStepAppendResult)
        assert (
            deterministic.created
            and ai_call.created
            and tool_call.created
            and skipped_ai_call.created
        )

        steps = list_agent_steps(db, run["id"])
        assert [row["step_number"] for row in steps] == [1, 2, 3, 4]
        assert [row["step_type"] for row in steps] == [
            "rule",
            "ai_call",
            "tool_call",
            "ai_call",
        ]
        assert steps[1]["completed_at"] is not None
        assert steps[2]["error_code"] == "tool_validation"
        assert steps[2]["error_message"] == "Quest title is required"

        refreshed = get_agent_run(db, run["id"])
        assert refreshed["step_count"] == 4
        # A skipped call is an audited decision, but it did not spend a call.
        assert refreshed["ai_call_count"] == 1
        assert refreshed["tool_call_count"] == 1
        assert refreshed["input_tokens"] == 120
        assert refreshed["output_tokens"] == 30
        assert refreshed["estimated_cost_microusd"] == 265


def test_step_key_is_idempotent_scoped_and_conflict_safe(audit_database):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        first_run = _create_run(db, session, message, request_key="first-run").run
        second_run = _create_run(db, session, message, request_key="second-run").run

        created = append_agent_step(
            db,
            run_id=first_run["id"],
            step_key=" call-model ",
            step_type=" ai_call ",
            name=" generate_response ",
            provider=" openai ",
            model=" test-model ",
            input_tokens=10,
            output_tokens=5,
            estimated_cost_microusd=20,
        )
        retry = append_agent_step(
            db,
            run_id=first_run["id"],
            step_key="call-model",
            step_type="ai_call",
            name="generate_response",
            provider="openai",
            model="test-model",
            input_tokens=10,
            output_tokens=5,
            estimated_cost_microusd=20,
        )
        same_key_other_run = append_agent_step(
            db,
            run_id=second_run["id"],
            step_key="call-model",
            step_type="ai_call",
            name="generate_response",
            provider="openai",
            model="test-model",
            input_tokens=10,
            output_tokens=5,
            estimated_cost_microusd=20,
        )

        assert created.created is True
        assert retry.created is False
        assert retry.duplicate is True
        assert retry.step["id"] == created.step["id"]
        assert same_key_other_run.created is True

        with pytest.raises(ValueError, match="different agent step"):
            append_agent_step(
                db,
                run_id=first_run["id"],
                step_key="call-model",
                step_type="ai_call",
                name="different_name",
                provider="openai",
                model="test-model",
                input_tokens=10,
                output_tokens=5,
                estimated_cost_microusd=20,
            )

        first_unkeyed = append_agent_step(
            db,
            run_id=first_run["id"],
            step_type="rule",
            name="repeatable_rule",
        )
        second_unkeyed = append_agent_step(
            db,
            run_id=first_run["id"],
            step_type="rule",
            name="repeatable_rule",
        )
        assert first_unkeyed.step["id"] != second_unkeyed.step["id"]
        assert get_agent_run(db, first_run["id"])["step_count"] == 3


@pytest.mark.parametrize(
    "invalid_values",
    [
        {"step_type": "", "name": "valid"},
        {"step_type": "rule", "name": "   "},
        {"step_type": "rule", "name": "valid", "status": "running"},
        {"step_type": "rule", "name": "valid", "input_tokens": -1},
        {"step_type": "rule", "name": "valid", "output_tokens": -1},
        {"step_type": "rule", "name": "valid", "input_tokens": 1.5},
        {"step_type": "rule", "name": "valid", "output_tokens": "1"},
        {
            "step_type": "rule",
            "name": "valid",
            "estimated_cost_microusd": True,
        },
        {
            "step_type": "rule",
            "name": "valid",
            "estimated_cost_microusd": -1,
        },
        {"step_type": "ai_call", "name": "generate"},
        {"step_type": "ai_call", "name": "generate", "provider": "openai"},
        {"step_type": "ai_call", "name": "generate", "model": "test-model"},
        {"step_type": "tool_call", "name": "execute_tool"},
        {
            "step_type": "ai_call",
            "name": "generate",
            "status": "failed",
            "provider": "openai",
            "model": "test-model",
        },
        {
            "step_type": "rule",
            "name": "valid",
            "status": "completed",
            "error_message": "completed with an error",
        },
    ],
)
def test_invalid_step_payload_does_not_partially_mutate_run(
    audit_database,
    invalid_values,
):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run

        with pytest.raises(ValueError):
            append_agent_step(db, run_id=run["id"], **invalid_values)

        assert list_agent_steps(db, run["id"]) == []
        unchanged = get_agent_run(db, run["id"])
        assert unchanged["step_count"] == 0
        assert unchanged["ai_call_count"] == 0
        assert unchanged["tool_call_count"] == 0
        assert unchanged["input_tokens"] == 0
        assert unchanged["output_tokens"] == 0
        assert unchanged["estimated_cost_microusd"] == 0


def test_terminal_finalization_is_idempotent_and_run_becomes_immutable(
    audit_database,
):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        created_run = _create_run(
            db,
            session,
            message,
            request_key="terminal-run",
        )
        run = created_run.run
        first_step = append_agent_step(
            db,
            run_id=run["id"],
            step_key="classify",
            step_type="rule",
            name="classify_intent",
        )

        completed = finalize_agent_run(db, run["id"], status="completed")
        retry = finalize_agent_run(db, run["id"], status="completed")

        assert completed["status"] == "completed"
        assert completed["completed_at"] is not None
        assert retry["id"] == completed["id"]
        assert retry["completed_at"] == completed["completed_at"]

        run_retry = _create_run(
            db,
            session,
            message,
            request_key="terminal-run",
        )
        step_retry = append_agent_step(
            db,
            run_id=run["id"],
            step_key="classify",
            step_type="rule",
            name="classify_intent",
        )
        assert run_retry.duplicate is True
        assert run_retry.run["status"] == "completed"
        assert step_retry.duplicate is True
        assert step_retry.step["id"] == first_step.step["id"]

        with pytest.raises(ValueError, match="already finalized"):
            finalize_agent_run(
                db,
                run["id"],
                status="failed",
                error_code="late_failure",
                error_message="This conflicts with completion",
            )
        with pytest.raises(ValueError, match="running"):
            append_agent_step(
                db,
                run_id=run["id"],
                step_type="rule",
                name="too_late",
            )
        with pytest.raises(ValueError, match="running"):
            set_agent_run_context(
                db,
                run["id"],
                intent="changed",
                loop_selected="changed_loop",
            )

        unchanged = get_agent_run(db, run["id"])
        assert unchanged["status"] == "completed"
        assert unchanged["step_count"] == 1
        assert unchanged["error_code"] is None
        assert unchanged["error_message"] is None


def test_failed_run_records_bounded_error_and_usage(audit_database):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run
        append_agent_step(
            db,
            run_id=run["id"],
            step_type="ai_call",
            name="generate_response",
            status="failed",
            provider="openai",
            model="test-model",
            input_tokens=80,
            output_tokens=4,
            estimated_cost_microusd=125,
            error_code="provider_timeout",
            error_message="Provider timed out",
        )

        failed = finalize_agent_run(
            db,
            run["id"],
            status="failed",
            error_code="provider_timeout",
            error_message="Provider timed out",
        )
        retry = finalize_agent_run(
            db,
            run["id"],
            status="failed",
            error_code="provider_timeout",
            error_message="Provider timed out",
        )

        assert failed["status"] == "failed"
        assert failed["error_code"] == "provider_timeout"
        assert failed["error_message"] == "Provider timed out"
        assert failed["ai_call_count"] == 1
        assert failed["input_tokens"] == 80
        assert failed["output_tokens"] == 4
        assert failed["estimated_cost_microusd"] == 125
        assert retry["completed_at"] == failed["completed_at"]


@pytest.mark.parametrize(
    ("status", "error_code", "error_message"),
    [
        ("running", None, None),
        ("invalid", None, None),
        ("failed", "provider_error", None),
        ("completed", "unexpected_error", "Completed runs cannot have errors"),
    ],
)
def test_invalid_finalization_leaves_run_running(
    audit_database,
    status,
    error_code,
    error_message,
):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run

        with pytest.raises(ValueError):
            finalize_agent_run(
                db,
                run["id"],
                status=status,
                error_code=error_code,
                error_message=error_message,
            )

        unchanged = get_agent_run(db, run["id"])
        assert unchanged["status"] == "running"
        assert unchanged["completed_at"] is None
        assert unchanged["error_code"] is None
        assert unchanged["error_message"] is None


def test_foreign_key_delete_policies_preserve_audit_until_run_is_deleted(
    audit_database,
):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run
        step = append_agent_step(
            db,
            run_id=run["id"],
            step_type="rule",
            name="classify_intent",
        ).step

        db.execute("DELETE FROM chat_messages WHERE id = ?", (message["id"],))
        after_message_delete = get_agent_run(db, run["id"])
        assert after_message_delete["session_id"] == session["id"]
        assert after_message_delete["user_message_id"] is None

        db.execute("DELETE FROM chat_sessions WHERE id = ?", (session["id"],))
        after_session_delete = get_agent_run(db, run["id"])
        assert after_session_delete["session_id"] is None
        assert after_session_delete["user_message_id"] is None
        assert list_agent_steps(db, run["id"])[0]["id"] == step["id"]

        db.execute("DELETE FROM agent_runs WHERE id = ?", (run["id"],))
        assert db.execute(
            "SELECT 1 FROM agent_steps WHERE id = ?", (step["id"],)
        ).fetchone() is None


def test_agent_audit_writes_roll_back_with_outer_transaction(audit_database):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        session_id = session["id"]
        message_id = message["id"]

    with pytest.raises(RuntimeError, match="force rollback"):
        with database.get_db() as db:
            run = create_agent_run(
                db,
                session_id=session_id,
                user_message_id=message_id,
                request_key="rolled-back-run",
                intent="chat",
                loop_selected="chat_loop",
            ).run
            append_agent_step(
                db,
                run_id=run["id"],
                step_type="ai_call",
                name="generate_response",
                provider="openai",
                model="test-model",
                input_tokens=20,
                output_tokens=10,
                estimated_cost_microusd=50,
            )
            finalize_agent_run(db, run["id"], status="completed")
            raise RuntimeError("force rollback")

    with database.get_db() as db:
        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM agent_steps").fetchone()[0] == 0


@pytest.mark.parametrize("source_mutation", ["archive_session", "delete_message"])
def test_run_retry_remains_idempotent_after_source_state_changes(
    audit_database,
    source_mutation,
):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        created = _create_run(
            db,
            session,
            message,
            request_key="source-state-retry",
        )

        if source_mutation == "archive_session":
            archive_chat_session(db, session["id"])
        else:
            delete_chat_message(db, message["id"], confirmed=True)

        retry = _create_run(
            db,
            session,
            message,
            request_key="source-state-retry",
        )
        assert retry.duplicate is True
        assert retry.run["id"] == created.run["id"]

        with pytest.raises(ValueError):
            _create_run(
                db,
                session,
                message,
                request_key="new-run-after-source-change",
            )
        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 1


@pytest.mark.parametrize("source_mutation", ["archive_session", "delete_message"])
def test_create_run_rechecks_source_state_atomically_at_insert(
    audit_database,
    source_mutation,
):
    class SourceMutationConnection:
        def __init__(self, connection, session_id, message_id):
            self.connection = connection
            self.session_id = session_id
            self.message_id = message_id
            self.mutated = False

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, sql, parameters=()):
            normalized_sql = " ".join(sql.split()).upper()
            if (
                not self.mutated
                and normalized_sql.startswith("INSERT INTO AGENT_RUNS")
            ):
                if source_mutation == "archive_session":
                    self.connection.execute(
                        "UPDATE chat_sessions SET status = 'archived' WHERE id = ?",
                        (self.session_id,),
                    )
                else:
                    self.connection.execute(
                        """
                        UPDATE chat_messages
                        SET deleted_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (self.message_id,),
                    )
                self.mutated = True
            return self.connection.execute(sql, parameters)

    with database.get_db() as db:
        session, message = _create_chat_input(db)

    with database.get_db() as db:
        racing_db = SourceMutationConnection(
            db,
            session["id"],
            message["id"],
        )
        with pytest.raises(ValueError):
            _create_run(
                racing_db,
                session,
                message,
                request_key="source-race",
            )

        assert racing_db.mutated is True
        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0


def test_append_rolls_back_its_step_when_aggregate_refresh_fails(
    audit_database,
):
    class AggregateFailureConnection:
        def __init__(self, connection):
            self.connection = connection
            self.failed = False

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, sql, parameters=()):
            normalized_sql = " ".join(sql.split()).upper()
            if (
                not self.failed
                and normalized_sql.startswith("UPDATE AGENT_RUNS")
                and "STEP_COUNT = (" in normalized_sql
            ):
                self.failed = True
                raise sqlite3.OperationalError("forced aggregate refresh failure")
            return self.connection.execute(sql, parameters)

    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run
        run_id = run["id"]

        failing_db = AggregateFailureConnection(db)
        with pytest.raises(
            sqlite3.OperationalError,
            match="forced aggregate refresh failure",
        ):
            append_agent_step(
                failing_db,
                run_id=run_id,
                step_type="rule",
                name="must_be_atomic",
            )

        assert failing_db.failed is True
        assert list_agent_steps(db, run_id) == []
        unchanged = get_agent_run(db, run_id)
        assert unchanged["step_count"] == 0
        assert unchanged["input_tokens"] == 0
        assert unchanged["output_tokens"] == 0
        assert unchanged["estimated_cost_microusd"] == 0

    # Catching the service error inside get_db must not make the partial step
    # eligible for the outer context manager's otherwise-normal commit.
    with database.get_db() as db:
        assert list_agent_steps(db, run_id) == []


def test_append_does_not_take_ownership_of_an_idle_outer_transaction(
    audit_database,
):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run_id = _create_run(db, session, message).run["id"]

    with pytest.raises(RuntimeError, match="rollback fresh connection"):
        with database.get_db() as db:
            assert db.in_transaction is False
            append_agent_step(
                db,
                run_id=run_id,
                step_type="rule",
                name="outer_transaction_owns_commit",
            )
            raise RuntimeError("rollback fresh connection")

    with database.get_db() as db:
        assert list_agent_steps(db, run_id) == []
        run = get_agent_run(db, run_id)
        assert run["step_count"] == 0
        assert run["ai_call_count"] == 0
        assert run["tool_call_count"] == 0
        assert run["input_tokens"] == 0
        assert run["output_tokens"] == 0
        assert run["estimated_cost_microusd"] == 0


@pytest.mark.parametrize(
    "usage_field",
    ["input_tokens", "output_tokens", "estimated_cost_microusd"],
)
def test_usage_values_above_sqlite_integer_range_are_rejected(
    audit_database,
    usage_field,
):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run
        payload = {
            "run_id": run["id"],
            "step_type": "ai_call",
            "name": "out_of_range_usage",
            "provider": "openai",
            "model": "test-model",
            usage_field: MAX_USAGE_VALUE + 1,
        }

        with pytest.raises(ValueError):
            append_agent_step(db, **payload)

        assert list_agent_steps(db, run["id"]) == []
        assert get_agent_run(db, run["id"])[usage_field] == 0


def test_maximum_usage_value_is_accepted_without_counter_drift(audit_database):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run
        append_agent_step(
            db,
            run_id=run["id"],
            step_type="ai_call",
            name="largest_supported_usage",
            provider="openai",
            model="test-model",
            input_tokens=MAX_USAGE_VALUE,
            output_tokens=MAX_USAGE_VALUE,
            estimated_cost_microusd=MAX_USAGE_VALUE,
        )

        steps = list_agent_steps(db, run["id"])
        assert [row["name"] for row in steps] == ["largest_supported_usage"]
        refreshed = get_agent_run(db, run["id"])
        assert refreshed["step_count"] == 1
        assert refreshed["ai_call_count"] == 1
        assert refreshed["input_tokens"] == MAX_USAGE_VALUE
        assert refreshed["output_tokens"] == MAX_USAGE_VALUE
        assert refreshed["estimated_cost_microusd"] == MAX_USAGE_VALUE


@pytest.mark.parametrize(
    "usage_payload",
    [
        {"input_tokens": 1},
        {"output_tokens": 1},
        {"estimated_cost_microusd": 1},
        {"provider": "openai"},
        {"model": "test-model"},
        {"provider": "openai", "model": "test-model"},
    ],
)
def test_non_call_steps_cannot_claim_ai_usage(
    audit_database,
    usage_payload,
):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run

        with pytest.raises(ValueError, match="AI-call|usage|tokens|cost|provider|model"):
            append_agent_step(
                db,
                run_id=run["id"],
                step_type="rule",
                name="misattributed_usage",
                **usage_payload,
            )

        assert list_agent_steps(db, run["id"]) == []
        assert get_agent_run(db, run["id"])["ai_call_count"] == 0


@pytest.mark.parametrize(
    "usage_payload",
    [
        {"input_tokens": 1},
        {"output_tokens": 1},
        {"provider": "openai"},
        {"model": "test-model"},
    ],
)
def test_tool_calls_reject_ai_metadata_but_may_record_direct_cost(
    audit_database,
    usage_payload,
):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run

        with pytest.raises(ValueError, match="AI-call|tokens|provider|model"):
            append_agent_step(
                db,
                run_id=run["id"],
                step_type="tool_call",
                name="misattributed_tool_usage",
                tool_name="create_quest",
                **usage_payload,
            )

        costed_tool = append_agent_step(
            db,
            run_id=run["id"],
            step_type="tool_call",
            name="paid_tool",
            tool_name="external_tool",
            estimated_cost_microusd=25,
        )
        assert costed_tool.created is True
        refreshed = get_agent_run(db, run["id"])
        assert refreshed["tool_call_count"] == 1
        assert refreshed["ai_call_count"] == 0
        assert refreshed["estimated_cost_microusd"] == 25


def test_error_summaries_redact_secrets_without_a_traceback(audit_database):
    unsafe_error = (
        "Provider rejected Authorization: Bearer sk-live-secret-123; "
        "api_key=sk-proj-supersecret password=hunter2 token=ghp_abcdef; "
        'payload={"password":"json secret with spaces","token":'
        '"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123"}'
    )
    forbidden_fragments = {
        "sk-live-secret-123",
        "sk-proj-supersecret",
        "hunter2",
        "ghp_abcdef",
        "json secret with spaces",
        "eyjhbgcioijiuzi1nij9",
    }

    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run
        failed_step = append_agent_step(
            db,
            run_id=run["id"],
            step_type="ai_call",
            name="provider_call",
            status="failed",
            provider="openai",
            model="test-model",
            error_code="provider_error",
            error_message=unsafe_error,
        ).step
        failed_run = finalize_agent_run(
            db,
            run["id"],
            status="failed",
            error_code="provider_error",
            error_message=unsafe_error,
        )

        for safe_summary in (
            failed_step["error_message"],
            failed_run["error_message"],
        ):
            assert safe_summary
            normalized_summary = safe_summary.lower()
            assert not any(
                fragment in normalized_summary for fragment in forbidden_fragments
            )


@pytest.mark.parametrize(
    "unsafe_error_code",
    [
        "provider timeout",
        "password=hunter2",
        "sk-live-secret-123",
        "ghp_abcdef123",
    ],
)
def test_error_codes_must_be_non_sensitive_symbolic_identifiers(
    audit_database,
    unsafe_error_code,
):
    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run

        with pytest.raises(ValueError, match="symbolic"):
            append_agent_step(
                db,
                run_id=run["id"],
                step_type="ai_call",
                name="provider_call",
                status="failed",
                provider="openai",
                model="test-model",
                error_code=unsafe_error_code,
                error_message="Curated provider failure",
            )

        assert list_agent_steps(db, run["id"]) == []


def test_error_summaries_remove_traceback_and_file_paths(audit_database):
    unsafe_traceback = """Traceback (most recent call last):
  File "/Users/private/agent.py", line 42, in call_provider
  File "/srv/mark-os/app/provider.py", line 7, in request
RuntimeError: Provider connection failed
"""

    with database.get_db() as db:
        session, message = _create_chat_input(db)
        run = _create_run(db, session, message).run
        failed_step = append_agent_step(
            db,
            run_id=run["id"],
            step_type="ai_call",
            name="provider_call",
            status="failed",
            provider="openai",
            model="test-model",
            error_code="provider_error",
            error_message=unsafe_traceback,
        ).step
        failed_run = finalize_agent_run(
            db,
            run["id"],
            status="failed",
            error_code="provider_error",
            error_message=unsafe_traceback,
        )

        for safe_summary in (
            failed_step["error_message"],
            failed_run["error_message"],
        ):
            assert safe_summary
            normalized_summary = safe_summary.lower()
            assert "traceback" not in normalized_summary
            assert "/users/private" not in normalized_summary
            assert "/srv/mark-os" not in normalized_summary
