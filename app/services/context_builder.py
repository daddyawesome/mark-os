from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace

from app.services.chat import get_recent_chat_messages
from app.services.memory import list_memories
from app.services.personal_scope import resolve_user_id


MAX_NEW_MESSAGE_LENGTH = 4_000

DEFAULT_MAX_MEMORIES = 5
MAX_MEMORIES_CAP = 10
DEFAULT_MAX_MESSAGES = 10
MAX_MESSAGES_CAP = 10
DEFAULT_MAX_GOALS = 3
MAX_GOALS_CAP = 10
DEFAULT_MAX_QUESTS = 3
MAX_QUESTS_CAP = 10

# Hard packet-size ceiling. Kept in characters (not tokens) so trimming is
# deterministic and provider-independent; ~4 characters per token is a
# conservative estimate for English text, so this bounds the packet to
# roughly 2,000 tokens before it ever reaches a paid provider.
MAX_CONTEXT_CHARACTERS = 8_000

# Only 'normal' sensitivity memories are eligible for AI-provider context.
# 'private' and 'restricted' memories remain fully usable by the app itself
# (Manual Memory Center, deterministic routing) but are never included in a
# packet that may be sent to an external model. This is the first consumer
# of the sensitivity field; see the memory form's "Classify before later AI
# use" guidance.
AI_ELIGIBLE_SENSITIVITY = "normal"

SYSTEM_IDENTITY = (
    "You are the MARK-OS assistant for this authenticated user only. You "
    "may read the bounded context provided with each request; you never "
    "have direct database access. You never reveal hidden XP thresholds, "
    "secrets, or another user's data. Suggestions, generated text, and "
    "reflections are not database writes and never award XP; only the "
    "user's own confirmed actions do that."
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "this", "that",
    "what", "when", "how", "why", "who", "will", "can", "should", "would",
    "about", "into", "from", "have", "has", "had", "was", "were", "are",
    "you", "your", "yours", "not", "just", "any", "all", "does",
}


def _bounded_text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    clean_value = value.strip()
    if not clean_value:
        raise ValueError(f"{field_name} is required")
    if len(clean_value) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer")
    return clean_value


def _bounded_count(value: int, *, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        safe_value = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(maximum, safe_value))


def estimate_tokens(text: str) -> int:
    """Conservative, provider-independent token estimate (~4 chars/token)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _keywords(text: str) -> set[str]:
    words = {
        word
        for word in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
        if len(word) >= 3 and word not in _STOPWORDS
    }
    return words


def _relevance_rank(memory: sqlite3.Row, message_keywords: set[str]) -> tuple[int, int, str]:
    memory_keywords = _keywords(f"{memory['memory_key']} {memory['memory_value']}")
    overlap = len(message_keywords & memory_keywords)
    return (overlap, int(memory["importance"]), str(memory["updated_at"]))


@dataclass(frozen=True)
class ContextPacket:
    system_identity: str
    profile_summary: dict | None
    level_progress: dict
    latest_checkin: dict | None
    goals: list[dict]
    quests: list[dict]
    memories: list[dict]
    messages: list[dict]
    crm_record: dict | None
    new_message: str
    estimated_tokens: int
    truncated: bool

    def to_provider_payload(self) -> dict:
        """A plain, JSON-safe dict in the bounded-context-packet order."""
        return {
            "system_identity": self.system_identity,
            "profile_summary": self.profile_summary,
            "level_progress": self.level_progress,
            "latest_checkin": self.latest_checkin,
            "goals": self.goals,
            "quests": self.quests,
            "crm_record": self.crm_record,
            "memories": self.memories,
            "messages": self.messages,
            "new_message": self.new_message,
        }


def _packet_size(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _load_profile_summary(db: sqlite3.Connection, user_id: int) -> dict | None:
    row = db.execute(
        "SELECT * FROM profile WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "name": row["name"],
        "wealth_goal": row["wealth_goal"],
        "weekday_hours": row["weekday_hours"],
        "weekend_rule": row["weekend_rule"],
        "strongest_skills": row["strongest_skills"],
        "primary_blocker": row["primary_blocker"],
    }


def _load_level_progress(db: sqlite3.Connection, user_id: int) -> dict:
    row = db.execute(
        "SELECT level, xp_total, xp_into_level, character_class FROM game_state WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return {
            "level": 1,
            "xp_total": 0,
            "xp_into_level": 0,
            "character_class": "Data Builder / Future Business Owner",
        }
    # Deliberately excludes threshold_mode / xp_required_for_next_level:
    # hidden XP thresholds must never enter provider context (Phase 8 rule).
    return {
        "level": row["level"],
        "xp_total": row["xp_total"],
        "xp_into_level": row["xp_into_level"],
        "character_class": row["character_class"],
    }


def _load_latest_checkin(db: sqlite3.Connection, user_id: int) -> dict | None:
    row = db.execute(
        """
        SELECT checkin_date, energy, accomplished, blocker, notes
        FROM checkins
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    # cash / expenses / free_hours are intentionally excluded: they are not
    # needed for coaching context and keep personal financial figures out of
    # any packet that may reach an external provider.
    return {
        "checkin_date": row["checkin_date"],
        "energy": row["energy"],
        "accomplished": row["accomplished"],
        "blocker": row["blocker"],
        "notes": row["notes"],
    }


def _load_goals(db: sqlite3.Connection, user_id: int, limit: int) -> list[dict]:
    if limit <= 0:
        return []
    rows = db.execute(
        """
        SELECT id, title, category, priority
        FROM goals
        WHERE user_id = ? AND status = 'active'
        ORDER BY priority DESC, id
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _load_quests(db: sqlite3.Connection, user_id: int, limit: int) -> list[dict]:
    if limit <= 0:
        return []
    rows = db.execute(
        """
        SELECT id, title, status, priority, progress, due_date, blocked_reason
        FROM tasks
        WHERE user_id = ? AND status NOT IN ('completed', 'abandoned', 'closed')
        ORDER BY
            CASE status WHEN 'active' THEN 0 WHEN 'blocked' THEN 1 ELSE 2 END,
            priority DESC,
            id
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _load_memories(
    db: sqlite3.Connection,
    user_id: int,
    *,
    limit: int,
    message_keywords: set[str],
) -> list[dict]:
    if limit <= 0:
        return []
    eligible = [
        memory
        for memory in list_memories(db, user_id=user_id)
        if memory["sensitivity"] == AI_ELIGIBLE_SENSITIVITY
    ]
    ranked = sorted(
        eligible,
        key=lambda memory: _relevance_rank(memory, message_keywords),
        reverse=True,
    )
    return [
        {
            "memory_type": memory["memory_type"],
            "memory_key": memory["memory_key"],
            "memory_value": memory["memory_value"],
            "importance": memory["importance"],
        }
        for memory in ranked[:limit]
    ]


def _load_messages(
    db: sqlite3.Connection,
    user_id: int,
    session_id: int | None,
    limit: int,
) -> list[dict]:
    if session_id is None or limit <= 0:
        return []
    rows = get_recent_chat_messages(db, session_id, limit=limit, user_id=user_id)
    return [
        {"role": row["role"], "content": row["content"]}
        for row in rows
    ]


def _trim_to_budget(
    *,
    goals: list[dict],
    quests: list[dict],
    memories: list[dict],
    messages: list[dict],
    fixed_payload: dict,
) -> tuple[list[dict], list[dict], list[dict], list[dict], bool]:
    truncated = False

    def total_size() -> int:
        payload = dict(fixed_payload)
        payload["goals"] = goals
        payload["quests"] = quests
        payload["memories"] = memories
        payload["messages"] = messages
        return _packet_size(payload)

    # Drop order: least essential first. Memories are enrichment; quests and
    # goals are secondary summaries; messages (most recent kept) matter most
    # for conversational continuity, so they are trimmed last and from the
    # oldest end.
    while total_size() > MAX_CONTEXT_CHARACTERS and memories:
        memories = memories[:-1]
        truncated = True
    while total_size() > MAX_CONTEXT_CHARACTERS and quests:
        quests = quests[:-1]
        truncated = True
    while total_size() > MAX_CONTEXT_CHARACTERS and goals:
        goals = goals[:-1]
        truncated = True
    while total_size() > MAX_CONTEXT_CHARACTERS and len(messages) > 1:
        messages = messages[1:]
        truncated = True

    return goals, quests, memories, messages, truncated


def build_context(
    db: sqlite3.Connection,
    *,
    new_message: str,
    user_id: int | None = None,
    session_id: int | None = None,
    max_memories: int = DEFAULT_MAX_MEMORIES,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_goals: int = DEFAULT_MAX_GOALS,
    max_quests: int = DEFAULT_MAX_QUESTS,
    crm_record: dict | None = None,
) -> ContextPacket:
    """Assemble the bounded, budget-safe AI context packet for one request.

    Deterministic SQLite filtering and ranking only; no embeddings. Scoped
    strictly to `user_id`. `crm_record` must already be authorized and
    summarized by the caller (this function performs no CRM lookups or
    workspace authorization of its own, so CRM access control is never
    duplicated outside its owning services).
    """
    safe_user_id = resolve_user_id(db, user_id)
    clean_message = _bounded_text(new_message, "Message", MAX_NEW_MESSAGE_LENGTH)

    safe_max_memories = _bounded_count(
        max_memories, default=DEFAULT_MAX_MEMORIES, maximum=MAX_MEMORIES_CAP
    )
    safe_max_messages = _bounded_count(
        max_messages, default=DEFAULT_MAX_MESSAGES, maximum=MAX_MESSAGES_CAP
    )
    safe_max_goals = _bounded_count(
        max_goals, default=DEFAULT_MAX_GOALS, maximum=MAX_GOALS_CAP
    )
    safe_max_quests = _bounded_count(
        max_quests, default=DEFAULT_MAX_QUESTS, maximum=MAX_QUESTS_CAP
    )

    profile_summary = _load_profile_summary(db, safe_user_id)
    level_progress = _load_level_progress(db, safe_user_id)
    latest_checkin = _load_latest_checkin(db, safe_user_id)
    goals = _load_goals(db, safe_user_id, safe_max_goals)
    quests = _load_quests(db, safe_user_id, safe_max_quests)
    memories = _load_memories(
        db,
        safe_user_id,
        limit=safe_max_memories,
        message_keywords=_keywords(clean_message),
    )
    messages = _load_messages(db, safe_user_id, session_id, safe_max_messages)

    fixed_payload = {
        "system_identity": SYSTEM_IDENTITY,
        "profile_summary": profile_summary,
        "level_progress": level_progress,
        "latest_checkin": latest_checkin,
        "crm_record": crm_record,
        "new_message": clean_message,
    }

    goals, quests, memories, messages, truncated = _trim_to_budget(
        goals=goals,
        quests=quests,
        memories=memories,
        messages=messages,
        fixed_payload=fixed_payload,
    )

    packet = ContextPacket(
        system_identity=SYSTEM_IDENTITY,
        profile_summary=profile_summary,
        level_progress=level_progress,
        latest_checkin=latest_checkin,
        goals=goals,
        quests=quests,
        memories=memories,
        messages=messages,
        crm_record=crm_record,
        new_message=clean_message,
        estimated_tokens=0,
        truncated=truncated,
    )
    final_size = _packet_size(packet.to_provider_payload())
    return replace(packet, estimated_tokens=max(1, (final_size + 3) // 4))
