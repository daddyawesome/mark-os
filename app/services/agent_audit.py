from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

DEFAULT_RUN_LIMIT = 50
MAX_RUN_LIMIT = 100

MAX_REQUEST_KEY_LENGTH = 255
MAX_STEP_KEY_LENGTH = 255
MAX_INTENT_LENGTH = 100
MAX_LOOP_LENGTH = 100
MAX_STEP_TYPE_LENGTH = 100
MAX_STEP_NAME_LENGTH = 200
MAX_TOOL_NAME_LENGTH = 200
MAX_PROVIDER_LENGTH = 100
MAX_MODEL_LENGTH = 200
MAX_ERROR_CODE_LENGTH = 100
MAX_ERROR_MESSAGE_LENGTH = 2_000
MAX_USAGE_VALUE = 1_000_000_000_000

_TRACEBACK_OR_PRIVATE_KEY = re.compile(
    r"traceback \(most recent call last\)|-----begin [^-]*private key-----",
    re.IGNORECASE,
)
_BEARER_TOKEN = re.compile(r"\bbearer\s+[^\s,;]+", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?P<key>(?<![a-z0-9_])[\"']?(?:password|passwd|client[_-]?secret|"
    r"private[_-]?key|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|token|authorization)[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_PROVIDER_SECRET = re.compile(
    r"\b(?:sk-[a-z0-9_-]{6,}|gh[pousr]_[a-z0-9_]{6,}|"
    r"github_pat_[a-z0-9_]{6,}|akia[a-z0-9]{16}|"
    r"eyj[a-z0-9_-]{5,}\.[a-z0-9_-]{5,}\.[a-z0-9_-]{5,})\b",
    re.IGNORECASE,
)
_SYMBOLIC_ERROR_CODE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*")

RUNNING_STATUS = "running"
DEFAULT_LOOP_SELECTED = "none"
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
VALID_RUN_STATUSES = {RUNNING_STATUS, *TERMINAL_RUN_STATUSES}
VALID_STEP_STATUSES = {"completed", "failed", "skipped"}


@dataclass(frozen=True)
class AgentRunCreateResult:
    run: sqlite3.Row
    created: bool

    @property
    def duplicate(self) -> bool:
        return not self.created


@dataclass(frozen=True)
class AgentStepAppendResult:
    step: sqlite3.Row
    created: bool

    @property
    def duplicate(self) -> bool:
        return not self.created


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _bounded_text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    clean_value = value.strip()
    if not clean_value:
        raise ValueError(f"{field_name} is required")
    if len(clean_value) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer")
    return clean_value


def _optional_bounded_text(
    value: str | None,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    clean_value = value.strip() or None
    if clean_value and len(clean_value) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer")
    return clean_value


def _nonnegative_integer(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    if value > MAX_USAGE_VALUE:
        raise ValueError(
            f"{field_name} exceeds the maximum supported audit usage value"
        )
    return value


def _sanitize_error_message(error_message: str | None) -> str | None:
    if error_message is None:
        return None
    if not isinstance(error_message, str):
        raise ValueError("Error message must be text")

    clean_message = error_message.strip()
    if not clean_message:
        return None
    if _TRACEBACK_OR_PRIVATE_KEY.search(clean_message):
        return "Internal error details redacted"

    clean_message = _BEARER_TOKEN.sub("Bearer [REDACTED]", clean_message)
    clean_message = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group('key')}[REDACTED]",
        clean_message,
    )
    clean_message = _PROVIDER_SECRET.sub("[REDACTED]", clean_message)
    clean_message = " ".join(clean_message.split())
    if len(clean_message) > MAX_ERROR_MESSAGE_LENGTH:
        clean_message = f"{clean_message[: MAX_ERROR_MESSAGE_LENGTH - 3]}..."
    return clean_message


def _normalize_error_code(error_code: str | None) -> str | None:
    clean_code = _optional_bounded_text(
        error_code,
        "Error code",
        MAX_ERROR_CODE_LENGTH,
    )
    if clean_code is None:
        return None

    clean_code = clean_code.lower()
    if not _SYMBOLIC_ERROR_CODE.fullmatch(clean_code) or _PROVIDER_SECRET.search(
        clean_code
    ):
        raise ValueError("Error code must be a non-sensitive symbolic identifier")
    return clean_code


def _normalize_request_key(request_key: str | None) -> str | None:
    return _optional_bounded_text(
        request_key,
        "Request key",
        MAX_REQUEST_KEY_LENGTH,
    )


def _normalize_step_key(step_key: str | None) -> str | None:
    return _optional_bounded_text(step_key, "Step key", MAX_STEP_KEY_LENGTH)


def _normalize_run_status(status: str) -> str:
    clean_status = _bounded_text(status, "Run status", 20).lower()
    if clean_status not in VALID_RUN_STATUSES:
        raise ValueError(f"Unsupported agent run status: {status}")
    return clean_status


def _normalize_terminal_run_status(status: str) -> str:
    clean_status = _normalize_run_status(status)
    if clean_status not in TERMINAL_RUN_STATUSES:
        raise ValueError("Agent run final status must be completed, failed, or cancelled")
    return clean_status


def _normalize_step_status(status: str) -> str:
    clean_status = _bounded_text(status, "Step status", 20).lower()
    if clean_status not in VALID_STEP_STATUSES:
        raise ValueError(f"Unsupported agent step status: {status}")
    return clean_status


def _validate_error_fields(
    *,
    status: str,
    error_code: str | None,
    error_message: str | None,
    failed_status: str = "failed",
) -> tuple[str | None, str | None]:
    # Store only sanitized, bounded summaries here. Raw prompts, model outputs,
    # tool arguments, credentials, and other request payloads do not belong in audit rows.
    clean_error_code = _normalize_error_code(error_code)
    clean_error_message = _sanitize_error_message(error_message)

    if status == failed_status and not clean_error_message:
        raise ValueError("Failed audit records require an error message")
    if status == "completed" and (clean_error_code or clean_error_message):
        raise ValueError("Completed audit records cannot contain an error")
    return clean_error_code, clean_error_message


def _get_agent_run_by_request_key(
    db: sqlite3.Connection,
    *,
    session_id: int,
    request_key: str,
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT * FROM agent_runs
        WHERE session_id = ? AND request_key = ?
        """,
        (session_id, request_key),
    ).fetchone()


def _get_agent_step_by_key(
    db: sqlite3.Connection,
    *,
    run_id: int,
    step_key: str,
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT * FROM agent_steps
        WHERE run_id = ? AND step_key = ?
        """,
        (run_id, step_key),
    ).fetchone()


def get_agent_run(
    db: sqlite3.Connection,
    run_id: int,
) -> sqlite3.Row | None:
    safe_run_id = _positive_id(run_id, "Agent run ID")
    return db.execute(
        "SELECT * FROM agent_runs WHERE id = ?",
        (safe_run_id,),
    ).fetchone()


def _require_agent_run(
    db: sqlite3.Connection,
    run_id: int,
) -> sqlite3.Row:
    run = get_agent_run(db, run_id)
    if not run:
        raise ValueError("Agent run not found")
    return run


def _require_running_agent_run(
    db: sqlite3.Connection,
    run_id: int,
) -> sqlite3.Row:
    run = _require_agent_run(db, run_id)
    if run["status"] != RUNNING_STATUS:
        raise ValueError("Only running agent runs can be changed")
    return run


def _require_active_user_message(
    db: sqlite3.Connection,
    *,
    session_id: int,
    user_message_id: int,
) -> None:
    session = db.execute(
        "SELECT * FROM chat_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not session:
        raise ValueError("Chat session not found")
    if session["status"] != "active":
        raise ValueError("Agent runs require an active chat session")

    message = db.execute(
        "SELECT * FROM chat_messages WHERE id = ?",
        (user_message_id,),
    ).fetchone()
    if not message:
        raise ValueError("Chat message not found")
    if message["session_id"] != session_id:
        raise ValueError("User message does not belong to the chat session")
    if message["role"] != "user":
        raise ValueError("Agent runs require a user chat message")
    if message["deleted_at"] is not None:
        raise ValueError("Agent runs require an active user chat message")


def _same_run_creation(
    run: sqlite3.Row,
    *,
    user_message_id: int,
) -> bool:
    # Context is intentionally excluded: intent, loop, provider, and model may
    # be enriched after creation. The initiating message is the immutable request.
    return run["user_message_id"] == user_message_id


def _idempotent_run_creation(
    db: sqlite3.Connection,
    *,
    session_id: int,
    user_message_id: int,
    request_key: str,
) -> AgentRunCreateResult | None:
    existing = _get_agent_run_by_request_key(
        db,
        session_id=session_id,
        request_key=request_key,
    )
    if not existing:
        return None
    if not _same_run_creation(
        existing,
        user_message_id=user_message_id,
    ):
        raise ValueError("Request key was already used for a different agent run")
    return AgentRunCreateResult(run=existing, created=False)


def create_agent_run(
    db: sqlite3.Connection,
    *,
    session_id: int,
    user_message_id: int,
    request_key: str | None = None,
    intent: str = "unknown",
    loop_selected: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> AgentRunCreateResult:
    safe_session_id = _positive_id(session_id, "Chat session ID")
    safe_user_message_id = _positive_id(user_message_id, "User message ID")
    clean_request_key = _normalize_request_key(request_key)
    clean_intent = _bounded_text(intent, "Intent", MAX_INTENT_LENGTH)
    clean_loop = (
        _optional_bounded_text(
            loop_selected,
            "Selected loop",
            MAX_LOOP_LENGTH,
        )
        or DEFAULT_LOOP_SELECTED
    )
    clean_provider = _optional_bounded_text(
        provider,
        "Provider",
        MAX_PROVIDER_LENGTH,
    )
    clean_model = _optional_bounded_text(model, "Model", MAX_MODEL_LENGTH)

    if clean_request_key:
        duplicate = _idempotent_run_creation(
            db,
            session_id=safe_session_id,
            user_message_id=safe_user_message_id,
            request_key=clean_request_key,
        )
        if duplicate:
            return duplicate

    try:
        cursor = db.execute(
            """
            INSERT INTO agent_runs
                (session_id, user_message_id, request_key, intent, status,
                 loop_selected, provider, model, started_at, created_at, updated_at)
            SELECT session.id,
                   message.id,
                   ?, ?, 'running', ?, ?, ?,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM chat_sessions AS session
            JOIN chat_messages AS message
              ON message.id = ? AND message.session_id = session.id
            WHERE session.id = ?
              AND session.status = 'active'
              AND message.role = 'user'
              AND message.deleted_at IS NULL
            """,
            (
                clean_request_key,
                clean_intent,
                clean_loop,
                clean_provider,
                clean_model,
                safe_user_message_id,
                safe_session_id,
            ),
        )
    except sqlite3.IntegrityError:
        if clean_request_key:
            duplicate = _idempotent_run_creation(
                db,
                session_id=safe_session_id,
                user_message_id=safe_user_message_id,
                request_key=clean_request_key,
            )
            if duplicate:
                return duplicate
        raise

    if cursor.rowcount != 1:
        # The INSERT ... SELECT predicate is the authoritative source-state
        # check. This second lookup is diagnostic only, so no invalid row can
        # slip in if the chat changes between validation and insertion.
        _require_active_user_message(
            db,
            session_id=safe_session_id,
            user_message_id=safe_user_message_id,
        )
        raise RuntimeError("Agent run could not be created")

    run = get_agent_run(db, cursor.lastrowid)
    if not run:
        raise RuntimeError("Created agent run could not be reloaded")
    return AgentRunCreateResult(run=run, created=True)


def list_agent_runs(
    db: sqlite3.Connection,
    *,
    session_id: int | None = None,
    status: str | None = None,
    limit: int = DEFAULT_RUN_LIMIT,
) -> list[sqlite3.Row]:
    conditions: list[str] = []
    parameters: list[object] = []

    if session_id is not None:
        conditions.append("session_id = ?")
        parameters.append(_positive_id(session_id, "Chat session ID"))
    if status is not None:
        conditions.append("status = ?")
        parameters.append(_normalize_run_status(status))

    try:
        safe_limit = int(limit)
    except (TypeError, ValueError):
        safe_limit = DEFAULT_RUN_LIMIT
    safe_limit = max(1, min(MAX_RUN_LIMIT, safe_limit))
    parameters.append(safe_limit)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return db.execute(
        f"""
        SELECT * FROM agent_runs
        {where_clause}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        parameters,
    ).fetchall()


def set_agent_run_context(
    db: sqlite3.Connection,
    run_id: int,
    *,
    intent: str | None = None,
    loop_selected: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> sqlite3.Row:
    safe_run_id = _positive_id(run_id, "Agent run ID")
    _require_running_agent_run(db, safe_run_id)

    clean_intent = (
        _bounded_text(intent, "Intent", MAX_INTENT_LENGTH)
        if intent is not None
        else None
    )
    clean_loop = _optional_bounded_text(
        loop_selected,
        "Selected loop",
        MAX_LOOP_LENGTH,
    )
    clean_provider = _optional_bounded_text(
        provider,
        "Provider",
        MAX_PROVIDER_LENGTH,
    )
    clean_model = _optional_bounded_text(model, "Model", MAX_MODEL_LENGTH)

    cursor = db.execute(
        """
        UPDATE agent_runs
        SET intent = COALESCE(?, intent),
            loop_selected = COALESCE(?, loop_selected),
            provider = COALESCE(?, provider),
            model = COALESCE(?, model),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'running'
        """,
        (clean_intent, clean_loop, clean_provider, clean_model, safe_run_id),
    )
    if cursor.rowcount != 1:
        _require_running_agent_run(db, safe_run_id)
        raise RuntimeError("Agent run context could not be updated")

    run = get_agent_run(db, safe_run_id)
    if not run:
        raise RuntimeError("Updated agent run could not be reloaded")
    return run


def _same_step_append(
    step: sqlite3.Row,
    *,
    step_type: str,
    name: str,
    status: str,
    tool_name: str | None,
    provider: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_microusd: int,
    error_code: str | None,
    error_message: str | None,
) -> bool:
    return (
        step["step_type"] == step_type
        and step["name"] == name
        and step["status"] == status
        and step["tool_name"] == tool_name
        and step["provider"] == provider
        and step["model"] == model
        and step["input_tokens"] == input_tokens
        and step["output_tokens"] == output_tokens
        and step["estimated_cost_microusd"] == estimated_cost_microusd
        and step["error_code"] == error_code
        and step["error_message"] == error_message
    )


def _idempotent_step_append(
    db: sqlite3.Connection,
    *,
    run_id: int,
    step_key: str,
    step_type: str,
    name: str,
    status: str,
    tool_name: str | None,
    provider: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_microusd: int,
    error_code: str | None,
    error_message: str | None,
) -> AgentStepAppendResult | None:
    existing = _get_agent_step_by_key(db, run_id=run_id, step_key=step_key)
    if not existing:
        return None
    if not _same_step_append(
        existing,
        step_type=step_type,
        name=name,
        status=status,
        tool_name=tool_name,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_microusd=estimated_cost_microusd,
        error_code=error_code,
        error_message=error_message,
    ):
        raise ValueError("Step key was already used for a different agent step")
    return AgentStepAppendResult(step=existing, created=False)


def _refresh_agent_run_totals(db: sqlite3.Connection, run_id: int) -> None:
    cursor = db.execute(
        """
        UPDATE agent_runs
        SET step_count = (
                SELECT COUNT(*) FROM agent_steps WHERE run_id = ?
            ),
            ai_call_count = (
                SELECT COUNT(*) FROM agent_steps
                WHERE run_id = ? AND step_type = 'ai_call' AND status != 'skipped'
            ),
            tool_call_count = (
                SELECT COUNT(*) FROM agent_steps
                WHERE run_id = ? AND step_type = 'tool_call' AND status != 'skipped'
            ),
            input_tokens = COALESCE((
                SELECT SUM(input_tokens) FROM agent_steps WHERE run_id = ?
            ), 0),
            output_tokens = COALESCE((
                SELECT SUM(output_tokens) FROM agent_steps WHERE run_id = ?
            ), 0),
            estimated_cost_microusd = COALESCE((
                SELECT SUM(estimated_cost_microusd)
                FROM agent_steps WHERE run_id = ?
            ), 0),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'running'
        """,
        (run_id, run_id, run_id, run_id, run_id, run_id, run_id),
    )
    if cursor.rowcount != 1:
        _require_running_agent_run(db, run_id)
        raise RuntimeError("Agent run totals could not be refreshed")


def append_agent_step(
    db: sqlite3.Connection,
    *,
    run_id: int,
    step_type: str,
    name: str,
    status: str = "completed",
    step_key: str | None = None,
    tool_name: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost_microusd: int = 0,
    error_code: str | None = None,
    error_message: str | None = None,
) -> AgentStepAppendResult:
    safe_run_id = _positive_id(run_id, "Agent run ID")
    clean_step_key = _normalize_step_key(step_key)
    clean_step_type = _bounded_text(
        step_type,
        "Step type",
        MAX_STEP_TYPE_LENGTH,
    ).lower()
    clean_name = _bounded_text(name, "Step name", MAX_STEP_NAME_LENGTH)
    clean_status = _normalize_step_status(status)
    clean_tool_name = _optional_bounded_text(
        tool_name,
        "Tool name",
        MAX_TOOL_NAME_LENGTH,
    )
    clean_provider = _optional_bounded_text(
        provider,
        "Provider",
        MAX_PROVIDER_LENGTH,
    )
    clean_model = _optional_bounded_text(model, "Model", MAX_MODEL_LENGTH)
    safe_input_tokens = _nonnegative_integer(input_tokens, "Input tokens")
    safe_output_tokens = _nonnegative_integer(output_tokens, "Output tokens")
    safe_cost = _nonnegative_integer(
        estimated_cost_microusd,
        "Estimated cost in micro-USD",
    )
    clean_error_code, clean_error_message = _validate_error_fields(
        status=clean_status,
        error_code=error_code,
        error_message=error_message,
    )

    if clean_step_type == "tool_call" and not clean_tool_name:
        raise ValueError("Tool-call steps require a tool name")
    if clean_step_type == "ai_call" and (not clean_provider or not clean_model):
        raise ValueError("AI-call steps require both a provider and model")
    if clean_step_type != "ai_call" and (clean_provider or clean_model):
        raise ValueError("Only AI-call steps can record a provider or model")
    if clean_step_type != "ai_call" and (safe_input_tokens or safe_output_tokens):
        raise ValueError("Only AI-call steps can record input or output tokens")
    if clean_step_type not in {"ai_call", "tool_call"} and safe_cost:
        raise ValueError("Only AI-call or tool-call steps can record cost")
    if clean_status == "skipped" and (
        safe_input_tokens or safe_output_tokens or safe_cost
    ):
        raise ValueError("Skipped steps cannot record tokens or cost")

    if clean_step_key:
        duplicate = _idempotent_step_append(
            db,
            run_id=safe_run_id,
            step_key=clean_step_key,
            step_type=clean_step_type,
            name=clean_name,
            status=clean_status,
            tool_name=clean_tool_name,
            provider=clean_provider,
            model=clean_model,
            input_tokens=safe_input_tokens,
            output_tokens=safe_output_tokens,
            estimated_cost_microusd=safe_cost,
            error_code=clean_error_code,
            error_message=clean_error_message,
        )
        if duplicate:
            return duplicate

    _require_running_agent_run(db, safe_run_id)

    # An outermost SAVEPOINT is committed by RELEASE in SQLite. Start a normal
    # transaction on an otherwise-idle connection so only the nested unit is
    # released here; the caller still owns the eventual commit or rollback.
    if not db.in_transaction:
        db.execute("BEGIN")
    db.execute("SAVEPOINT agent_step_append")

    try:
        try:
            cursor = db.execute(
                """
                INSERT INTO agent_steps
                    (run_id, step_number, step_key, step_type, name, status,
                     tool_name, provider, model, input_tokens, output_tokens,
                     estimated_cost_microusd, error_code, error_message,
                     started_at, completed_at, created_at, updated_at)
                SELECT r.id,
                       COALESCE(MAX(s.step_number), 0) + 1,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM agent_runs AS r
                LEFT JOIN agent_steps AS s ON s.run_id = r.id
                WHERE r.id = ? AND r.status = 'running'
                GROUP BY r.id
                """,
                (
                    clean_step_key,
                    clean_step_type,
                    clean_name,
                    clean_status,
                    clean_tool_name,
                    clean_provider,
                    clean_model,
                    safe_input_tokens,
                    safe_output_tokens,
                    safe_cost,
                    clean_error_code,
                    clean_error_message,
                    safe_run_id,
                ),
            )
        except sqlite3.IntegrityError:
            if clean_step_key:
                duplicate = _idempotent_step_append(
                    db,
                    run_id=safe_run_id,
                    step_key=clean_step_key,
                    step_type=clean_step_type,
                    name=clean_name,
                    status=clean_status,
                    tool_name=clean_tool_name,
                    provider=clean_provider,
                    model=clean_model,
                    input_tokens=safe_input_tokens,
                    output_tokens=safe_output_tokens,
                    estimated_cost_microusd=safe_cost,
                    error_code=clean_error_code,
                    error_message=clean_error_message,
                )
                if duplicate:
                    db.execute("RELEASE SAVEPOINT agent_step_append")
                    return duplicate
            raise

        if cursor.rowcount != 1:
            _require_running_agent_run(db, safe_run_id)
            raise RuntimeError("Agent step could not be appended")

        step = db.execute(
            "SELECT * FROM agent_steps WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        if not step:
            raise RuntimeError("Appended agent step could not be reloaded")

        _refresh_agent_run_totals(db, safe_run_id)
    except Exception as exc:
        db.execute("ROLLBACK TO SAVEPOINT agent_step_append")
        db.execute("RELEASE SAVEPOINT agent_step_append")
        if isinstance(exc, sqlite3.OperationalError) and "integer overflow" in str(
            exc
        ).lower():
            raise ValueError("Agent run usage totals exceed SQLite's integer range") from exc
        raise

    db.execute("RELEASE SAVEPOINT agent_step_append")
    return AgentStepAppendResult(step=step, created=True)


def list_agent_steps(
    db: sqlite3.Connection,
    run_id: int,
) -> list[sqlite3.Row]:
    safe_run_id = _positive_id(run_id, "Agent run ID")
    _require_agent_run(db, safe_run_id)
    return db.execute(
        """
        SELECT * FROM agent_steps
        WHERE run_id = ?
        ORDER BY step_number ASC, id ASC
        """,
        (safe_run_id,),
    ).fetchall()


def finalize_agent_run(
    db: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> sqlite3.Row:
    safe_run_id = _positive_id(run_id, "Agent run ID")
    clean_status = _normalize_terminal_run_status(status)
    clean_error_code, clean_error_message = _validate_error_fields(
        status=clean_status,
        error_code=error_code,
        error_message=error_message,
    )

    run = _require_agent_run(db, safe_run_id)
    if run["status"] != RUNNING_STATUS:
        if (
            run["status"] == clean_status
            and run["error_code"] == clean_error_code
            and run["error_message"] == clean_error_message
        ):
            return run
        raise ValueError("Agent run is already finalized with a different result")

    _refresh_agent_run_totals(db, safe_run_id)
    cursor = db.execute(
        """
        UPDATE agent_runs
        SET status = ?,
            error_code = ?,
            error_message = ?,
            completed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'running'
        """,
        (clean_status, clean_error_code, clean_error_message, safe_run_id),
    )
    if cursor.rowcount != 1:
        current = _require_agent_run(db, safe_run_id)
        if (
            current["status"] == clean_status
            and current["error_code"] == clean_error_code
            and current["error_message"] == clean_error_message
        ):
            return current
        raise ValueError("Agent run was finalized concurrently with a different result")

    finalized = get_agent_run(db, safe_run_id)
    if not finalized:
        raise RuntimeError("Finalized agent run could not be reloaded")
    return finalized
