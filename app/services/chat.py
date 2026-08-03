from __future__ import annotations

import sqlite3
from dataclasses import dataclass

DEFAULT_CHAT_TITLE = "New chat"
DEFAULT_RECENT_MESSAGES = 10
MAX_RECENT_MESSAGES = 10
MAX_TITLE_LENGTH = 200
MAX_REQUEST_KEY_LENGTH = 255
VALID_CHAT_ROLES = {"user", "assistant", "system", "tool"}


@dataclass(frozen=True)
class ChatMessageSaveResult:
    message: sqlite3.Row
    created: bool

    @property
    def duplicate(self) -> bool:
        return not self.created


def _normalize_title(title: str | None) -> str:
    clean_title = (title or "").strip() or DEFAULT_CHAT_TITLE
    if len(clean_title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Chat title must be {MAX_TITLE_LENGTH} characters or fewer")
    return clean_title


def _normalize_role(role: str) -> str:
    clean_role = (role or "").strip().lower()
    if clean_role not in VALID_CHAT_ROLES:
        raise ValueError(f"Unsupported chat role: {role}")
    return clean_role


def _normalize_content(content: str) -> str:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Chat message content is required")
    return content


def _normalize_request_key(request_key: str | None) -> str | None:
    clean_key = (request_key or "").strip() or None
    if clean_key and len(clean_key) > MAX_REQUEST_KEY_LENGTH:
        raise ValueError(
            f"Request key must be {MAX_REQUEST_KEY_LENGTH} characters or fewer"
        )
    return clean_key


def _require_chat_session(
    db: sqlite3.Connection,
    session_id: int,
) -> sqlite3.Row:
    session = get_chat_session(db, session_id)
    if not session:
        raise ValueError("Chat session not found")
    return session


def _get_chat_message(
    db: sqlite3.Connection,
    message_id: int,
) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM chat_messages WHERE id = ?",
        (message_id,),
    ).fetchone()


def _refresh_session_activity(db: sqlite3.Connection, session_id: int) -> None:
    db.execute(
        """
        UPDATE chat_sessions
        SET last_message_at = (
                SELECT created_at
                FROM chat_messages
                WHERE session_id = ? AND deleted_at IS NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (session_id, session_id),
    )


def create_chat_session(
    db: sqlite3.Connection,
    *,
    title: str | None = None,
) -> sqlite3.Row:
    cursor = db.execute(
        """
        INSERT INTO chat_sessions (title, status, created_at, updated_at)
        VALUES (?, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (_normalize_title(title),),
    )
    return _require_chat_session(db, cursor.lastrowid)


def get_chat_session(
    db: sqlite3.Connection,
    session_id: int,
) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM chat_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()


def list_chat_sessions(
    db: sqlite3.Connection,
    *,
    include_archived: bool = False,
) -> list[sqlite3.Row]:
    if include_archived:
        return db.execute(
            """
            SELECT * FROM chat_sessions
            ORDER BY COALESCE(last_message_at, updated_at, created_at) DESC, id DESC
            """
        ).fetchall()

    return db.execute(
        """
        SELECT * FROM chat_sessions
        WHERE status = 'active'
        ORDER BY COALESCE(last_message_at, updated_at, created_at) DESC, id DESC
        """
    ).fetchall()


def rename_chat_session(
    db: sqlite3.Connection,
    session_id: int,
    *,
    title: str,
) -> sqlite3.Row:
    _require_chat_session(db, session_id)
    db.execute(
        """
        UPDATE chat_sessions
        SET title = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (_normalize_title(title), session_id),
    )
    return _require_chat_session(db, session_id)


def archive_chat_session(
    db: sqlite3.Connection,
    session_id: int,
) -> sqlite3.Row:
    _require_chat_session(db, session_id)
    db.execute(
        """
        UPDATE chat_sessions
        SET status = 'archived',
            archived_at = COALESCE(archived_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (session_id,),
    )
    return _require_chat_session(db, session_id)


def delete_chat_session(
    db: sqlite3.Connection,
    session_id: int,
    *,
    confirmed: bool = False,
) -> bool:
    if confirmed is not True:
        raise ValueError("Chat session deletion requires confirmation")

    _require_chat_session(db, session_id)
    db.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    return True


def delete_or_archive_chat_session(
    db: sqlite3.Connection,
    session_id: int,
    *,
    hard_delete: bool = False,
    confirmed: bool = False,
) -> sqlite3.Row | bool:
    if hard_delete is True:
        return delete_chat_session(db, session_id, confirmed=confirmed)
    return archive_chat_session(db, session_id)


def _idempotent_message(
    db: sqlite3.Connection,
    *,
    session_id: int,
    role: str,
    content: str,
    request_key: str,
) -> ChatMessageSaveResult | None:
    existing = db.execute(
        """
        SELECT * FROM chat_messages
        WHERE session_id = ? AND request_key = ?
        """,
        (session_id, request_key),
    ).fetchone()
    if not existing:
        return None
    if existing["role"] != role or existing["content"] != content:
        raise ValueError("Request key was already used for a different chat message")
    return ChatMessageSaveResult(message=existing, created=False)


def save_chat_message(
    db: sqlite3.Connection,
    *,
    session_id: int,
    role: str,
    content: str,
    request_key: str | None = None,
) -> ChatMessageSaveResult:
    session = _require_chat_session(db, session_id)
    clean_role = _normalize_role(role)
    clean_content = _normalize_content(content)
    clean_request_key = _normalize_request_key(request_key)

    if clean_request_key:
        duplicate = _idempotent_message(
            db,
            session_id=session_id,
            role=clean_role,
            content=clean_content,
            request_key=clean_request_key,
        )
        if duplicate:
            return duplicate

    if session["status"] != "active":
        raise ValueError("Cannot add a message to an archived chat session")

    try:
        cursor = db.execute(
            """
            INSERT INTO chat_messages
                (session_id, role, content, request_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (session_id, clean_role, clean_content, clean_request_key),
        )
    except sqlite3.IntegrityError:
        if clean_request_key:
            duplicate = _idempotent_message(
                db,
                session_id=session_id,
                role=clean_role,
                content=clean_content,
                request_key=clean_request_key,
            )
            if duplicate:
                return duplicate
        raise

    message = _get_chat_message(db, cursor.lastrowid)
    if not message:
        raise RuntimeError("Saved chat message could not be reloaded")

    db.execute(
        """
        UPDATE chat_sessions
        SET last_message_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (message["created_at"], session_id),
    )
    return ChatMessageSaveResult(message=message, created=True)


def edit_chat_message(
    db: sqlite3.Connection,
    message_id: int,
    *,
    content: str,
) -> sqlite3.Row:
    message = _get_chat_message(db, message_id)
    if not message:
        raise ValueError("Chat message not found")
    if message["deleted_at"] is not None:
        raise ValueError("Deleted chat messages cannot be edited")

    db.execute(
        """
        UPDATE chat_messages
        SET content = ?, edited_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (_normalize_content(content), message_id),
    )
    db.execute(
        """
        UPDATE chat_sessions
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (message["session_id"],),
    )
    updated = _get_chat_message(db, message_id)
    if not updated:
        raise RuntimeError("Edited chat message could not be reloaded")
    return updated


def delete_chat_message(
    db: sqlite3.Connection,
    message_id: int,
    *,
    confirmed: bool = False,
    hard_delete: bool = False,
) -> bool:
    if confirmed is not True:
        raise ValueError("Chat message deletion requires confirmation")

    message = _get_chat_message(db, message_id)
    if not message:
        raise ValueError("Chat message not found")

    if hard_delete is True:
        db.execute("DELETE FROM chat_messages WHERE id = ?", (message_id,))
    else:
        db.execute(
            """
            UPDATE chat_messages
            SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (message_id,),
        )

    _refresh_session_activity(db, message["session_id"])
    return True


def delete_or_soft_delete_chat_message(
    db: sqlite3.Connection,
    message_id: int,
    *,
    hard_delete: bool = False,
    confirmed: bool = False,
) -> bool:
    return delete_chat_message(
        db,
        message_id,
        confirmed=confirmed,
        hard_delete=hard_delete,
    )


def get_recent_chat_messages(
    db: sqlite3.Connection,
    session_id: int,
    *,
    limit: int = DEFAULT_RECENT_MESSAGES,
) -> list[sqlite3.Row]:
    _require_chat_session(db, session_id)
    try:
        safe_limit = int(limit)
    except (TypeError, ValueError):
        safe_limit = DEFAULT_RECENT_MESSAGES
    safe_limit = max(1, min(MAX_RECENT_MESSAGES, safe_limit))

    return db.execute(
        """
        SELECT *
        FROM (
            SELECT *
            FROM chat_messages
            WHERE session_id = ? AND deleted_at IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        ) AS recent_messages
        ORDER BY created_at ASC, id ASC
        """,
        (session_id, safe_limit),
    ).fetchall()
