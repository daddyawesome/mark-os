from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from app.services.personal_scope import resolve_user_id


MAX_TYPE_LENGTH = 100
MAX_KEY_LENGTH = 200
MAX_VALUE_LENGTH = 10_000
MAX_SOURCE_LENGTH = 100
MAX_REASON_LENGTH = 1_000
MAX_REQUEST_KEY_LENGTH = 255
VALID_SENSITIVITIES = {"normal", "private", "restricted"}

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)
_BEARER_TOKEN = re.compile(r"\bbearer\s+[a-z0-9._~+/-]{8,}", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"\b(?:password|passwd|client[_-]?secret|private[_-]?key|secret|"
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)"
    r"\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_PROVIDER_SECRET = re.compile(
    r"\b(?:sk-[a-z0-9_-]{8,}|gh[pousr]_[a-z0-9_]{8,}|"
    r"github_pat_[a-z0-9_]{8,}|akia[a-z0-9]{16})\b",
    re.IGNORECASE,
)
_BANKING_INFORMATION = re.compile(
    r"\b(?:bank\s+account|account\s+number|routing\s+number|iban|"
    r"swift\s*(?:code)?|credit\s+card|debit\s+card)\b\s*[:=]?\s*"
    r"[a-z0-9 -]{4,}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MemoryCandidateCreateResult:
    candidate: sqlite3.Row
    created: bool

    @property
    def duplicate(self) -> bool:
        return not self.created


@dataclass(frozen=True)
class MemoryAcceptanceResult:
    candidate: sqlite3.Row
    memory: sqlite3.Row
    memory_created: bool
    superseded_memory_id: int | None = None


class MemoryConflictError(ValueError):
    """Raised when a submitted memory version is no longer current."""


def _bounded_text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    clean_value = value.strip()
    if not clean_value:
        raise ValueError(f"{field_name} is required")
    if len(clean_value) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer")
    return clean_value


def _optional_text(
    value: str | None,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    clean_value = _bounded_text(value, field_name, maximum)
    return clean_value


def _importance(value: int) -> int:
    if isinstance(value, bool):
        raise ValueError("Importance must be an integer from 1 to 10")
    try:
        safe_value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Importance must be an integer from 1 to 10") from exc
    if safe_value < 1 or safe_value > 10:
        raise ValueError("Importance must be an integer from 1 to 10")
    return safe_value


def _confidence(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("Confidence must be between 0 and 1")
    try:
        safe_value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Confidence must be between 0 and 1") from exc
    if not 0.0 <= safe_value <= 1.0:
        raise ValueError("Confidence must be between 0 and 1")
    return safe_value


def _positive_optional_id(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer")
    try:
        safe_value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if safe_value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return safe_value


def _reject_prohibited_content(*values: str | None) -> None:
    content = "\n".join(value for value in values if value)
    if any(
        pattern.search(content)
        for pattern in (
            _PRIVATE_KEY,
            _BEARER_TOKEN,
            _SECRET_ASSIGNMENT,
            _PROVIDER_SECRET,
            _BANKING_INFORMATION,
        )
    ):
        raise ValueError("Secrets and banking information cannot be stored as memory")


def _content_hash(
    *,
    memory_type: str,
    memory_key: str,
    memory_value: str,
    importance: int,
    sensitivity: str,
) -> str:
    payload = json.dumps(
        {
            "importance": importance,
            "memory_key": memory_key,
            "memory_type": memory_type,
            "memory_value": memory_value,
            "sensitivity": sensitivity,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@contextmanager
def _atomic(db: sqlite3.Connection, savepoint: str) -> Iterator[None]:
    if not db.in_transaction:
        db.execute("BEGIN")
    db.execute(f"SAVEPOINT {savepoint}")
    try:
        yield
    except Exception:
        db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        db.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    db.execute(f"RELEASE SAVEPOINT {savepoint}")


def _record_event(
    db: sqlite3.Connection,
    *,
    user_id: int,
    event_type: str,
    source: str,
    memory_id: int | None = None,
    candidate_id: int | None = None,
    agent_run_id: int | None = None,
    details: dict[str, int | str | bool | None] | None = None,
) -> None:
    safe_details = {
        str(key): value
        for key, value in (details or {}).items()
        if isinstance(value, (str, int, bool)) or value is None
    }
    db.execute(
        """
        INSERT INTO memory_audit_events (
            user_id,
            event_type,
            actor_user_id,
            memory_id,
            candidate_id,
            agent_run_id,
            source,
            details_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            event_type,
            user_id,
            memory_id,
            candidate_id,
            agent_run_id,
            source,
            json.dumps(safe_details, sort_keys=True, separators=(",", ":")),
        ),
    )


def get_memory_candidate(
    db: sqlite3.Connection,
    candidate_id: int,
    *,
    user_id: int | None = None,
) -> sqlite3.Row | None:
    safe_user_id = resolve_user_id(db, user_id)
    safe_candidate_id = _positive_optional_id(candidate_id, "Candidate ID")
    return db.execute(
        "SELECT * FROM memory_candidates WHERE id = ? AND user_id = ?",
        (safe_candidate_id, safe_user_id),
    ).fetchone()


def get_memory(
    db: sqlite3.Connection,
    memory_id: int,
    *,
    user_id: int | None = None,
) -> sqlite3.Row | None:
    safe_user_id = resolve_user_id(db, user_id)
    safe_memory_id = _positive_optional_id(memory_id, "Memory ID")
    return db.execute(
        "SELECT * FROM memories WHERE id = ? AND user_id = ?",
        (safe_memory_id, safe_user_id),
    ).fetchone()


def list_memories(
    db: sqlite3.Connection,
    *,
    include_archived: bool = False,
    user_id: int | None = None,
) -> list[sqlite3.Row]:
    safe_user_id = resolve_user_id(db, user_id)
    active_filter = "" if include_archived else "AND active = 1"
    return db.execute(
        f"""
        SELECT * FROM memories
        WHERE user_id = ? {active_filter}
        ORDER BY active DESC, importance DESC, updated_at DESC, id DESC
        """,
        (safe_user_id,),
    ).fetchall()


def list_memory_candidates(
    db: sqlite3.Connection,
    *,
    status: str = "pending",
    user_id: int | None = None,
) -> list[sqlite3.Row]:
    safe_user_id = resolve_user_id(db, user_id)
    clean_status = _bounded_text(status, "Candidate status", 20).lower()
    if clean_status not in {"pending", "accepted", "rejected", "archived"}:
        raise ValueError("Unsupported memory candidate status")
    return db.execute(
        """
        SELECT * FROM memory_candidates
        WHERE user_id = ? AND status = ?
        ORDER BY importance DESC, created_at DESC, id DESC
        """,
        (safe_user_id, clean_status),
    ).fetchall()


def list_memory_audit_events(
    db: sqlite3.Connection,
    *,
    limit: int = 25,
    user_id: int | None = None,
) -> list[sqlite3.Row]:
    safe_user_id = resolve_user_id(db, user_id)
    try:
        safe_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("Audit limit must be an integer") from exc
    if safe_limit < 1 or safe_limit > 100:
        raise ValueError("Audit limit must be between 1 and 100")
    return db.execute(
        """
        SELECT * FROM memory_audit_events
        WHERE user_id = ?
        ORDER BY occurred_at DESC, id DESC
        LIMIT ?
        """,
        (safe_user_id, safe_limit),
    ).fetchall()


def _validated_memory_fields(
    *,
    memory_type: str,
    memory_key: str,
    memory_value: str,
    importance: int,
    source: str,
    confidence: float,
    sensitivity: str,
) -> tuple[str, str, str, int, str, float, str, str]:
    clean_type = _bounded_text(memory_type, "Memory type", MAX_TYPE_LENGTH)
    clean_key = _bounded_text(memory_key, "Memory key", MAX_KEY_LENGTH)
    clean_value = _bounded_text(memory_value, "Memory value", MAX_VALUE_LENGTH)
    safe_importance = _importance(importance)
    clean_source = _bounded_text(source, "Source", MAX_SOURCE_LENGTH)
    safe_confidence = _confidence(confidence)
    clean_sensitivity = _bounded_text(sensitivity, "Sensitivity", 20).lower()
    if clean_sensitivity not in VALID_SENSITIVITIES:
        raise ValueError("Unsupported memory sensitivity")
    _reject_prohibited_content(clean_type, clean_key, clean_value, clean_source)
    fingerprint = _content_hash(
        memory_type=clean_type,
        memory_key=clean_key,
        memory_value=clean_value,
        importance=safe_importance,
        sensitivity=clean_sensitivity,
    )
    return (
        clean_type,
        clean_key,
        clean_value,
        safe_importance,
        clean_source,
        safe_confidence,
        clean_sensitivity,
        fingerprint,
    )


def create_memory(
    db: sqlite3.Connection,
    *,
    memory_type: str,
    memory_key: str,
    memory_value: str,
    importance: int = 5,
    source: str = "manual",
    confidence: float = 1.0,
    sensitivity: str = "normal",
    user_id: int | None = None,
) -> sqlite3.Row:
    safe_user_id = resolve_user_id(db, user_id)
    (
        clean_type,
        clean_key,
        clean_value,
        safe_importance,
        clean_source,
        safe_confidence,
        clean_sensitivity,
        fingerprint,
    ) = _validated_memory_fields(
        memory_type=memory_type,
        memory_key=memory_key,
        memory_value=memory_value,
        importance=importance,
        source=source,
        confidence=confidence,
        sensitivity=sensitivity,
    )
    existing = db.execute(
        """
        SELECT id FROM memories
        WHERE user_id = ? AND memory_key = ? AND active = 1
        """,
        (safe_user_id, clean_key),
    ).fetchone()
    if existing is not None:
        raise ValueError("An active memory already uses this key")

    next_version = int(
        db.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1
            FROM memories
            WHERE user_id = ? AND memory_key = ?
            """,
            (safe_user_id, clean_key),
        ).fetchone()[0]
    )
    with _atomic(db, "manual_memory_create"):
        cursor = db.execute(
            """
            INSERT INTO memories (
                user_id, memory_type, memory_key, memory_value, importance,
                source, active, confidence, sensitivity, version, content_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                safe_user_id,
                clean_type,
                clean_key,
                clean_value,
                safe_importance,
                clean_source,
                safe_confidence,
                clean_sensitivity,
                next_version,
                fingerprint,
            ),
        )
        memory_id = int(cursor.lastrowid)
        _record_event(
            db,
            user_id=safe_user_id,
            event_type="memory_created",
            source="manual_memory_center",
            memory_id=memory_id,
            details={"version": next_version},
        )
    memory = get_memory(db, memory_id, user_id=safe_user_id)
    if memory is None:
        raise RuntimeError("Created memory could not be reloaded")
    return memory


def revise_memory(
    db: sqlite3.Connection,
    memory_id: int,
    *,
    expected_version: int,
    memory_type: str,
    memory_value: str,
    importance: int,
    source: str,
    confidence: float,
    sensitivity: str,
    user_id: int | None = None,
) -> sqlite3.Row:
    safe_user_id = resolve_user_id(db, user_id)
    current = get_memory(db, memory_id, user_id=safe_user_id)
    if current is None:
        raise ValueError("Memory not found")
    if isinstance(expected_version, bool):
        raise ValueError("Expected version must be an integer")
    try:
        safe_expected_version = int(expected_version)
    except (TypeError, ValueError) as exc:
        raise ValueError("Expected version must be an integer") from exc
    if not current["active"] or int(current["version"]) != safe_expected_version:
        raise MemoryConflictError(
            "This memory changed after the edit page was opened"
        )

    (
        clean_type,
        clean_key,
        clean_value,
        safe_importance,
        clean_source,
        safe_confidence,
        clean_sensitivity,
        fingerprint,
    ) = _validated_memory_fields(
        memory_type=memory_type,
        memory_key=current["memory_key"],
        memory_value=memory_value,
        importance=importance,
        source=source,
        confidence=confidence,
        sensitivity=sensitivity,
    )
    next_version = safe_expected_version + 1

    with _atomic(db, "manual_memory_revise"):
        cursor = db.execute(
            """
            UPDATE memories
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND active = 1 AND version = ?
            """,
            (int(current["id"]), safe_user_id, safe_expected_version),
        )
        if cursor.rowcount != 1:
            raise MemoryConflictError(
                "This memory changed after the edit page was opened"
            )
        cursor = db.execute(
            """
            INSERT INTO memories (
                user_id, memory_type, memory_key, memory_value, importance,
                source, active, confidence, sensitivity, version, content_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                safe_user_id,
                clean_type,
                clean_key,
                clean_value,
                safe_importance,
                clean_source,
                safe_confidence,
                clean_sensitivity,
                next_version,
                fingerprint,
            ),
        )
        replacement_id = int(cursor.lastrowid)
        db.execute(
            """
            UPDATE memories
            SET superseded_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND active = 0
            """,
            (replacement_id, int(current["id"]), safe_user_id),
        )
        _record_event(
            db,
            user_id=safe_user_id,
            event_type="memory_superseded",
            source="manual_memory_center",
            memory_id=int(current["id"]),
            details={"replacement_memory_id": replacement_id},
        )
        _record_event(
            db,
            user_id=safe_user_id,
            event_type="memory_created",
            source="manual_memory_center",
            memory_id=replacement_id,
            details={"version": next_version},
        )
    replacement = get_memory(db, replacement_id, user_id=safe_user_id)
    if replacement is None:
        raise RuntimeError("Revised memory could not be reloaded")
    return replacement


def _candidate_by_request_key(
    db: sqlite3.Connection,
    *,
    user_id: int,
    request_key: str,
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT * FROM memory_candidates
        WHERE user_id = ? AND request_key = ?
        """,
        (user_id, request_key),
    ).fetchone()


def _pending_candidate_by_hash(
    db: sqlite3.Connection,
    *,
    user_id: int,
    content_hash: str,
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT * FROM memory_candidates
        WHERE user_id = ? AND content_hash = ? AND status = 'pending'
        """,
        (user_id, content_hash),
    ).fetchone()


def _same_candidate_request(
    candidate: sqlite3.Row,
    *,
    memory_type: str,
    memory_key: str,
    memory_value: str,
    importance: int,
    source: str,
    source_type: str | None,
    source_id: int | None,
    agent_run_id: int | None,
    confidence: float,
    sensitivity: str,
    candidate_reason: str,
    content_hash: str,
) -> bool:
    return (
        candidate["memory_type"] == memory_type
        and candidate["memory_key"] == memory_key
        and candidate["memory_value"] == memory_value
        and candidate["importance"] == importance
        and candidate["source"] == source
        and candidate["source_type"] == source_type
        and candidate["source_id"] == source_id
        and candidate["agent_run_id"] == agent_run_id
        and candidate["confidence"] == confidence
        and candidate["sensitivity"] == sensitivity
        and candidate["candidate_reason"] == candidate_reason
        and candidate["content_hash"] == content_hash
    )


def create_memory_candidate(
    db: sqlite3.Connection,
    *,
    memory_type: str,
    memory_key: str,
    memory_value: str,
    source: str,
    candidate_reason: str,
    importance: int = 5,
    source_type: str | None = None,
    source_id: int | None = None,
    agent_run_id: int | None = None,
    confidence: float = 1.0,
    sensitivity: str = "normal",
    request_key: str | None = None,
    user_id: int | None = None,
) -> MemoryCandidateCreateResult:
    safe_user_id = resolve_user_id(db, user_id)
    clean_type = _bounded_text(memory_type, "Memory type", MAX_TYPE_LENGTH)
    clean_key = _bounded_text(memory_key, "Memory key", MAX_KEY_LENGTH)
    clean_value = _bounded_text(memory_value, "Memory value", MAX_VALUE_LENGTH)
    clean_source = _bounded_text(source, "Source", MAX_SOURCE_LENGTH)
    clean_reason = _bounded_text(candidate_reason, "Candidate reason", MAX_REASON_LENGTH)
    safe_importance = _importance(importance)
    clean_source_type = _optional_text(source_type, "Source type", MAX_TYPE_LENGTH)
    safe_source_id = _positive_optional_id(source_id, "Source ID")
    safe_agent_run_id = _positive_optional_id(agent_run_id, "Agent run ID")
    safe_confidence = _confidence(confidence)
    clean_sensitivity = _bounded_text(sensitivity, "Sensitivity", 20).lower()
    if clean_sensitivity not in VALID_SENSITIVITIES:
        raise ValueError("Unsupported memory sensitivity")
    clean_request_key = _optional_text(
        request_key,
        "Request key",
        MAX_REQUEST_KEY_LENGTH,
    )
    if safe_source_id is not None and clean_source_type is None:
        raise ValueError("Source type is required when source ID is provided")
    _reject_prohibited_content(
        clean_type,
        clean_key,
        clean_value,
        clean_source,
        clean_reason,
    )

    if safe_agent_run_id is not None:
        run = db.execute(
            "SELECT id FROM agent_runs WHERE id = ? AND user_id = ?",
            (safe_agent_run_id, safe_user_id),
        ).fetchone()
        if run is None:
            raise ValueError("Agent run not found")

    fingerprint = _content_hash(
        memory_type=clean_type,
        memory_key=clean_key,
        memory_value=clean_value,
        importance=safe_importance,
        sensitivity=clean_sensitivity,
    )

    if clean_request_key:
        existing = _candidate_by_request_key(
            db,
            user_id=safe_user_id,
            request_key=clean_request_key,
        )
        if existing is not None:
            if not _same_candidate_request(
                existing,
                memory_type=clean_type,
                memory_key=clean_key,
                memory_value=clean_value,
                importance=safe_importance,
                source=clean_source,
                source_type=clean_source_type,
                source_id=safe_source_id,
                agent_run_id=safe_agent_run_id,
                confidence=safe_confidence,
                sensitivity=clean_sensitivity,
                candidate_reason=clean_reason,
                content_hash=fingerprint,
            ):
                raise ValueError(
                    "Request key was already used for a different memory candidate"
                )
            return MemoryCandidateCreateResult(existing, created=False)

    duplicate = _pending_candidate_by_hash(
        db,
        user_id=safe_user_id,
        content_hash=fingerprint,
    )
    if duplicate is not None:
        return MemoryCandidateCreateResult(duplicate, created=False)

    try:
        with _atomic(db, "memory_candidate_create"):
            cursor = db.execute(
                """
                INSERT INTO memory_candidates (
                    user_id, memory_type, memory_key, memory_value, importance,
                    source, source_type, source_id, agent_run_id, confidence,
                    sensitivity, candidate_reason, status, content_hash,
                    request_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    safe_user_id,
                    clean_type,
                    clean_key,
                    clean_value,
                    safe_importance,
                    clean_source,
                    clean_source_type,
                    safe_source_id,
                    safe_agent_run_id,
                    safe_confidence,
                    clean_sensitivity,
                    clean_reason,
                    fingerprint,
                    clean_request_key,
                ),
            )
            candidate_id = int(cursor.lastrowid)
            _record_event(
                db,
                user_id=safe_user_id,
                event_type="candidate_created",
                source=clean_source,
                candidate_id=candidate_id,
                agent_run_id=safe_agent_run_id,
                details={"sensitivity": clean_sensitivity},
            )
    except sqlite3.IntegrityError:
        existing = (
            _candidate_by_request_key(
                db,
                user_id=safe_user_id,
                request_key=clean_request_key,
            )
            if clean_request_key
            else None
        ) or _pending_candidate_by_hash(
            db,
            user_id=safe_user_id,
            content_hash=fingerprint,
        )
        if existing is not None and existing["content_hash"] == fingerprint:
            return MemoryCandidateCreateResult(existing, created=False)
        raise

    candidate = get_memory_candidate(db, candidate_id, user_id=safe_user_id)
    if candidate is None:
        raise RuntimeError("Created memory candidate could not be reloaded")
    return MemoryCandidateCreateResult(candidate, created=True)


def _require_candidate(
    db: sqlite3.Connection,
    candidate_id: int,
    user_id: int,
) -> sqlite3.Row:
    candidate = get_memory_candidate(db, candidate_id, user_id=user_id)
    if candidate is None:
        raise ValueError("Memory candidate not found")
    return candidate


def accept_memory_candidate(
    db: sqlite3.Connection,
    candidate_id: int,
    *,
    user_id: int | None = None,
) -> MemoryAcceptanceResult:
    safe_user_id = resolve_user_id(db, user_id)
    candidate = _require_candidate(db, candidate_id, safe_user_id)
    if candidate["status"] == "accepted":
        memory = get_memory(
            db,
            int(candidate["accepted_memory_id"]),
            user_id=safe_user_id,
        )
        if memory is None:
            raise RuntimeError("Accepted memory candidate has no durable memory")
        return MemoryAcceptanceResult(candidate, memory, memory_created=False)
    if candidate["status"] != "pending":
        raise ValueError("Only pending memory candidates can be accepted")

    _reject_prohibited_content(
        candidate["memory_type"],
        candidate["memory_key"],
        candidate["memory_value"],
        candidate["source"],
        candidate["candidate_reason"],
    )
    existing = db.execute(
        """
        SELECT * FROM memories
        WHERE user_id = ? AND memory_key = ? AND active = 1
        """,
        (safe_user_id, candidate["memory_key"]),
    ).fetchone()

    with _atomic(db, "memory_candidate_accept"):
        memory_created = True
        superseded_memory_id: int | None = None
        if (
            existing is not None
            and existing["content_hash"] == candidate["content_hash"]
        ):
            memory = existing
            memory_created = False
        else:
            next_version = int(
                db.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1
                    FROM memories
                    WHERE user_id = ? AND memory_key = ?
                    """,
                    (safe_user_id, candidate["memory_key"]),
                ).fetchone()[0]
            )
            if existing is not None:
                superseded_memory_id = int(existing["id"])
                db.execute(
                    """
                    UPDATE memories
                    SET active = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ? AND active = 1
                    """,
                    (superseded_memory_id, safe_user_id),
                )

            cursor = db.execute(
                """
                INSERT INTO memories (
                    user_id, memory_type, memory_key, memory_value, importance,
                    source, active, source_type, source_id, confidence,
                    sensitivity, version, content_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    safe_user_id,
                    candidate["memory_type"],
                    candidate["memory_key"],
                    candidate["memory_value"],
                    candidate["importance"],
                    candidate["source"],
                    candidate["source_type"],
                    candidate["source_id"],
                    candidate["confidence"],
                    candidate["sensitivity"],
                    next_version,
                    candidate["content_hash"],
                ),
            )
            memory_id = int(cursor.lastrowid)
            if superseded_memory_id is not None:
                db.execute(
                    """
                    UPDATE memories
                    SET superseded_by = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ? AND active = 0
                    """,
                    (memory_id, superseded_memory_id, safe_user_id),
                )
                _record_event(
                    db,
                    user_id=safe_user_id,
                    event_type="memory_superseded",
                    source="candidate_acceptance",
                    memory_id=superseded_memory_id,
                    candidate_id=int(candidate["id"]),
                    agent_run_id=candidate["agent_run_id"],
                    details={"replacement_memory_id": memory_id},
                )
            memory = get_memory(db, memory_id, user_id=safe_user_id)
            if memory is None:
                raise RuntimeError("Accepted memory could not be reloaded")
            _record_event(
                db,
                user_id=safe_user_id,
                event_type="memory_created",
                source="candidate_acceptance",
                memory_id=memory_id,
                candidate_id=int(candidate["id"]),
                agent_run_id=candidate["agent_run_id"],
                details={"version": next_version},
            )

        cursor = db.execute(
            """
            UPDATE memory_candidates
            SET status = 'accepted',
                accepted_memory_id = ?,
                resolved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND status = 'pending'
            """,
            (int(memory["id"]), int(candidate["id"]), safe_user_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Memory candidate changed before acceptance")
        _record_event(
            db,
            user_id=safe_user_id,
            event_type="candidate_accepted",
            source="candidate_acceptance",
            memory_id=int(memory["id"]),
            candidate_id=int(candidate["id"]),
            agent_run_id=candidate["agent_run_id"],
            details={"memory_created": memory_created},
        )

    resolved = _require_candidate(db, candidate_id, safe_user_id)
    return MemoryAcceptanceResult(
        resolved,
        memory,
        memory_created=memory_created,
        superseded_memory_id=superseded_memory_id,
    )


def reject_memory_candidate(
    db: sqlite3.Connection,
    candidate_id: int,
    *,
    reason: str,
    user_id: int | None = None,
) -> sqlite3.Row:
    safe_user_id = resolve_user_id(db, user_id)
    clean_reason = _bounded_text(reason, "Rejection reason", MAX_REASON_LENGTH)
    _reject_prohibited_content(clean_reason)
    candidate = _require_candidate(db, candidate_id, safe_user_id)
    if candidate["status"] == "rejected":
        if candidate["resolution_reason"] != clean_reason:
            raise ValueError("Memory candidate was rejected with a different reason")
        return candidate
    if candidate["status"] != "pending":
        raise ValueError("Only pending memory candidates can be rejected")

    with _atomic(db, "memory_candidate_reject"):
        db.execute(
            """
            UPDATE memory_candidates
            SET status = 'rejected', resolution_reason = ?,
                resolved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND status = 'pending'
            """,
            (clean_reason, int(candidate["id"]), safe_user_id),
        )
        _record_event(
            db,
            user_id=safe_user_id,
            event_type="candidate_rejected",
            source="candidate_review",
            candidate_id=int(candidate["id"]),
            agent_run_id=candidate["agent_run_id"],
        )
    return _require_candidate(db, candidate_id, safe_user_id)


def archive_memory_candidate(
    db: sqlite3.Connection,
    candidate_id: int,
    *,
    reason: str | None = None,
    user_id: int | None = None,
) -> sqlite3.Row:
    safe_user_id = resolve_user_id(db, user_id)
    clean_reason = _optional_text(reason, "Archive reason", MAX_REASON_LENGTH)
    _reject_prohibited_content(clean_reason)
    candidate = _require_candidate(db, candidate_id, safe_user_id)
    if candidate["status"] == "archived":
        if candidate["resolution_reason"] != clean_reason:
            raise ValueError("Memory candidate was archived with a different reason")
        return candidate
    if candidate["status"] != "pending":
        raise ValueError("Only pending memory candidates can be archived")

    with _atomic(db, "memory_candidate_archive"):
        db.execute(
            """
            UPDATE memory_candidates
            SET status = 'archived', resolution_reason = ?,
                resolved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND status = 'pending'
            """,
            (clean_reason, int(candidate["id"]), safe_user_id),
        )
        _record_event(
            db,
            user_id=safe_user_id,
            event_type="candidate_archived",
            source="candidate_review",
            candidate_id=int(candidate["id"]),
            agent_run_id=candidate["agent_run_id"],
        )
    return _require_candidate(db, candidate_id, safe_user_id)


def archive_memory(
    db: sqlite3.Connection,
    memory_id: int,
    *,
    expected_version: int | None = None,
    user_id: int | None = None,
) -> sqlite3.Row:
    safe_user_id = resolve_user_id(db, user_id)
    memory = get_memory(db, memory_id, user_id=safe_user_id)
    if memory is None:
        raise ValueError("Memory not found")
    if expected_version is not None:
        if isinstance(expected_version, bool):
            raise ValueError("Expected version must be an integer")
        try:
            safe_expected_version = int(expected_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("Expected version must be an integer") from exc
        if (
            int(memory["version"]) != safe_expected_version
            or not memory["active"]
        ):
            raise MemoryConflictError(
                "This memory changed after the page was opened"
            )
    if memory["active"] == 0:
        return memory

    with _atomic(db, "memory_archive"):
        cursor = db.execute(
            """
            UPDATE memories
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND active = 1
              AND (? IS NULL OR version = ?)
            """,
            (
                int(memory["id"]),
                safe_user_id,
                expected_version,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise MemoryConflictError(
                "This memory changed after the page was opened"
            )
        _record_event(
            db,
            user_id=safe_user_id,
            event_type="memory_archived",
            source="memory_lifecycle",
            memory_id=int(memory["id"]),
            details={"version": int(memory["version"])},
        )

    archived = get_memory(db, memory_id, user_id=safe_user_id)
    if archived is None:
        raise RuntimeError("Archived memory could not be reloaded")
    return archived
