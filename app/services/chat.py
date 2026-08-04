from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.services.personal_scope import resolve_user_id


DEFAULT_CHAT_TITLE = "New chat"
DEFAULT_RECENT_MESSAGES = 10
MAX_RECENT_MESSAGES = 10
MAX_TITLE_LENGTH = 200
MAX_REQUEST_KEY_LENGTH = 255
VALID_CHAT_ROLES = {
    "user",
    "assistant",
    "system",
    "tool",
}


@dataclass(frozen=True)
class ChatMessageSaveResult:
    message: sqlite3.Row
    created: bool

    @property
    def duplicate(self) -> bool:
        return not self.created


def _normalize_title(title: str | None) -> str:
    clean_title = (
        (title or "").strip()
        or DEFAULT_CHAT_TITLE
    )
    if len(clean_title) > MAX_TITLE_LENGTH:
        raise ValueError(
            f"Chat title must be "
            f"{MAX_TITLE_LENGTH} characters or fewer"
        )
    return clean_title


def _normalize_role(role: str) -> str:
    clean_role = (role or "").strip().lower()
    if clean_role not in VALID_CHAT_ROLES:
        raise ValueError(
            f"Unsupported chat role: {role}"
        )
    return clean_role


def _normalize_content(content: str) -> str:
    if (
        not isinstance(content, str)
        or not content.strip()
    ):
        raise ValueError(
            "Chat message content is required"
        )
    return content


def _normalize_request_key(
    request_key: str | None,
) -> str | None:
    clean_key = (
        (request_key or "").strip()
        or None
    )
    if (
        clean_key
        and len(clean_key) > MAX_REQUEST_KEY_LENGTH
    ):
        raise ValueError(
            f"Request key must be "
            f"{MAX_REQUEST_KEY_LENGTH} characters or fewer"
        )
    return clean_key


def get_chat_session(
    db: sqlite3.Connection,
    session_id: int,
    *,
    user_id: int | None = None,
) -> sqlite3.Row | None:
    safe_user_id = resolve_user_id(db, user_id)
    return db.execute(
        """
        SELECT *
        FROM chat_sessions
        WHERE id = ? AND user_id = ?
        """,
        (session_id, safe_user_id),
    ).fetchone()


def _require_chat_session(
    db: sqlite3.Connection,
    session_id: int,
    *,
    user_id: int | None = None,
) -> sqlite3.Row:
    session = get_chat_session(
        db,
        session_id,
        user_id=user_id,
    )
    if not session:
        raise ValueError("Chat session not found")
    return session


def _get_chat_message(
    db: sqlite3.Connection,
    message_id: int,
    *,
    user_id: int | None = None,
) -> sqlite3.Row | None:
    safe_user_id = resolve_user_id(db, user_id)
    return db.execute(
        """
        SELECT *
        FROM chat_messages
        WHERE id = ? AND user_id = ?
        """,
        (message_id, safe_user_id),
    ).fetchone()


def _refresh_session_activity(
    db: sqlite3.Connection,
    session_id: int,
    user_id: int,
) -> None:
    db.execute(
        """
        UPDATE chat_sessions
        SET last_message_at = (
                SELECT created_at
                FROM chat_messages
                WHERE session_id = ?
                  AND user_id = ?
                  AND deleted_at IS NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (
            session_id,
            user_id,
            session_id,
            user_id,
        ),
    )


def create_chat_session(
    db: sqlite3.Connection,
    *,
    title: str | None = None,
    user_id: int | None = None,
) -> sqlite3.Row:
    safe_user_id = resolve_user_id(db, user_id)
    cursor = db.execute(
        """
        INSERT INTO chat_sessions (
            user_id,
            title,
            status,
            created_at,
            updated_at
        )
        VALUES (
            ?,
            ?,
            'active',
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        """,
        (
            safe_user_id,
            _normalize_title(title),
        ),
    )
    return _require_chat_session(
        db,
        int(cursor.lastrowid),
        user_id=safe_user_id,
    )


def list_chat_sessions(
    db: sqlite3.Connection,
    *,
    include_archived: bool = False,
    user_id: int | None = None,
) -> list[sqlite3.Row]:
    safe_user_id = resolve_user_id(db, user_id)
    if include_archived:
        return db.execute(
            """
            SELECT *
            FROM chat_sessions
            WHERE user_id = ?
            ORDER BY
                COALESCE(
                    last_message_at,
                    updated_at,
                    created_at
                ) DESC,
                id DESC
            """,
            (safe_user_id,),
        ).fetchall()

    return db.execute(
        """
        SELECT *
        FROM chat_sessions
        WHERE user_id = ? AND status = 'active'
        ORDER BY
            COALESCE(
                last_message_at,
                updated_at,
                created_at
            ) DESC,
            id DESC
        """,
        (safe_user_id,),
    ).fetchall()


def rename_chat_session(
    db: sqlite3.Connection,
    session_id: int,
    *,
    title: str,
    user_id: int | None = None,
) -> sqlite3.Row:
    safe_user_id = resolve_user_id(db, user_id)
    _require_chat_session(
        db,
        session_id,
        user_id=safe_user_id,
    )
    db.execute(
        """
        UPDATE chat_sessions
        SET title = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (
            _normalize_title(title),
            session_id,
            safe_user_id,
        ),
    )
    return _require_chat_session(
        db,
        session_id,
        user_id=safe_user_id,
    )


def archive_chat_session(
    db: sqlite3.Connection,
    session_id: int,
    *,
    user_id: int | None = None,
) -> sqlite3.Row:
    safe_user_id = resolve_user_id(db, user_id)
    _require_chat_session(
        db,
        session_id,
        user_id=safe_user_id,
    )
    db.execute(
        """
        UPDATE chat_sessions
        SET status = 'archived',
            archived_at = COALESCE(
                archived_at,
                CURRENT_TIMESTAMP
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (session_id, safe_user_id),
    )
    return _require_chat_session(
        db,
        session_id,
        user_id=safe_user_id,
    )


def delete_chat_session(
    db: sqlite3.Connection,
    session_id: int,
    *,
    confirmed: bool = False,
    user_id: int | None = None,
) -> bool:
    if confirmed is not True:
        raise ValueError(
            "Chat session deletion requires confirmation"
        )

    safe_user_id = resolve_user_id(db, user_id)
    _require_chat_session(
        db,
        session_id,
        user_id=safe_user_id,
    )
    db.execute(
        """
        DELETE FROM chat_sessions
        WHERE id = ? AND user_id = ?
        """,
        (session_id, safe_user_id),
    )
    return True


def delete_or_archive_chat_session(
    db: sqlite3.Connection,
    session_id: int,
    *,
    hard_delete: bool = False,
    confirmed: bool = False,
    user_id: int | None = None,
) -> sqlite3.Row | bool:
    if hard_delete is True:
        return delete_chat_session(
            db,
            session_id,
            confirmed=confirmed,
            user_id=user_id,
        )
    return archive_chat_session(
        db,
        session_id,
        user_id=user_id,
    )


def _idempotent_message(
    db: sqlite3.Connection,
    *,
    session_id: int,
    role: str,
    content: str,
    request_key: str,
    user_id: int,
) -> ChatMessageSaveResult | None:
    existing = db.execute(
        """
        SELECT *
        FROM chat_messages
        WHERE session_id = ?
          AND user_id = ?
          AND request_key = ?
        """,
        (
            session_id,
            user_id,
            request_key,
        ),
    ).fetchone()
    if not existing:
        return None
    if (
        existing["role"] != role
        or existing["content"] != content
    ):
        raise ValueError(
            "Request key was already used for a "
            "different chat message"
        )
    return ChatMessageSaveResult(
        message=existing,
        created=False,
    )


def save_chat_message(
    db: sqlite3.Connection,
    *,
    session_id: int,
    role: str,
    content: str,
    request_key: str | None = None,
    user_id: int | None = None,
) -> ChatMessageSaveResult:
    safe_user_id = resolve_user_id(db, user_id)
    session = _require_chat_session(
        db,
        session_id,
        user_id=safe_user_id,
    )
    clean_role = _normalize_role(role)
    clean_content = _normalize_content(content)
    clean_request_key = _normalize_request_key(
        request_key
    )

    if clean_request_key:
        duplicate = _idempotent_message(
            db,
            session_id=session_id,
            role=clean_role,
            content=clean_content,
            request_key=clean_request_key,
            user_id=safe_user_id,
        )
        if duplicate:
            return duplicate

    if session["status"] != "active":
        raise ValueError(
            "Cannot add a message to an archived chat session"
        )

    try:
        cursor = db.execute(
            """
            INSERT INTO chat_messages (
                user_id,
                session_id,
                role,
                content,
                request_key,
                created_at,
                updated_at
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            """,
            (
                safe_user_id,
                session_id,
                clean_role,
                clean_content,
                clean_request_key,
            ),
        )
    except sqlite3.IntegrityError:
        if clean_request_key:
            duplicate = _idempotent_message(
                db,
                session_id=session_id,
                role=clean_role,
                content=clean_content,
                request_key=clean_request_key,
                user_id=safe_user_id,
            )
            if duplicate:
                return duplicate
        raise

    message = _get_chat_message(
        db,
        int(cursor.lastrowid),
        user_id=safe_user_id,
    )
    if not message:
        raise RuntimeError(
            "Saved chat message could not be reloaded"
        )

    db.execute(
        """
        UPDATE chat_sessions
        SET last_message_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (
            message["created_at"],
            session_id,
            safe_user_id,
        ),
    )
    return ChatMessageSaveResult(
        message=message,
        created=True,
    )


def edit_chat_message(
    db: sqlite3.Connection,
    message_id: int,
    *,
    content: str,
    user_id: int | None = None,
) -> sqlite3.Row:
    safe_user_id = resolve_user_id(db, user_id)
    message = _get_chat_message(
        db,
        message_id,
        user_id=safe_user_id,
    )
    if not message:
        raise ValueError("Chat message not found")
    if message["deleted_at"] is not None:
        raise ValueError(
            "Deleted chat messages cannot be edited"
        )

    db.execute(
        """
        UPDATE chat_messages
        SET content = ?,
            edited_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (
            _normalize_content(content),
            message_id,
            safe_user_id,
        ),
    )
    db.execute(
        """
        UPDATE chat_sessions
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (
            message["session_id"],
            safe_user_id,
        ),
    )

    updated = _get_chat_message(
        db,
        message_id,
        user_id=safe_user_id,
    )
    if not updated:
        raise RuntimeError(
            "Edited chat message could not be reloaded"
        )
    return updated


def delete_chat_message(
    db: sqlite3.Connection,
    message_id: int,
    *,
    confirmed: bool = False,
    hard_delete: bool = False,
    user_id: int | None = None,
) -> bool:
    if confirmed is not True:
        raise ValueError(
            "Chat message deletion requires confirmation"
        )

    safe_user_id = resolve_user_id(db, user_id)
    message = _get_chat_message(
        db,
        message_id,
        user_id=safe_user_id,
    )
    if not message:
        raise ValueError("Chat message not found")

    if hard_delete is True:
        db.execute(
            """
            DELETE FROM chat_messages
            WHERE id = ? AND user_id = ?
            """,
            (message_id, safe_user_id),
        )
    else:
        db.execute(
            """
            UPDATE chat_messages
            SET deleted_at = COALESCE(
                    deleted_at,
                    CURRENT_TIMESTAMP
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (message_id, safe_user_id),
        )

    _refresh_session_activity(
        db,
        message["session_id"],
        safe_user_id,
    )
    return True


def delete_or_soft_delete_chat_message(
    db: sqlite3.Connection,
    message_id: int,
    *,
    hard_delete: bool = False,
    confirmed: bool = False,
    user_id: int | None = None,
) -> bool:
    return delete_chat_message(
        db,
        message_id,
        confirmed=confirmed,
        hard_delete=hard_delete,
        user_id=user_id,
    )


def get_recent_chat_messages(
    db: sqlite3.Connection,
    session_id: int,
    *,
    limit: int = DEFAULT_RECENT_MESSAGES,
    user_id: int | None = None,
) -> list[sqlite3.Row]:
    safe_user_id = resolve_user_id(db, user_id)
    _require_chat_session(
        db,
        session_id,
        user_id=safe_user_id,
    )

    try:
        safe_limit = int(limit)
    except (TypeError, ValueError):
        safe_limit = DEFAULT_RECENT_MESSAGES
    safe_limit = max(
        1,
        min(MAX_RECENT_MESSAGES, safe_limit),
    )

    return db.execute(
        """
        SELECT *
        FROM (
            SELECT *
            FROM chat_messages
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        ) AS recent_messages
        ORDER BY created_at ASC, id ASC
        """,
        (
            session_id,
            safe_user_id,
            safe_limit,
        ),
    ).fetchall()
