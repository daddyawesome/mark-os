from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.services.agent_audit import (
    create_agent_run,
    finalize_agent_run,
    set_agent_run_context,
)
from app.services.chat import save_chat_message
from app.services.context_builder import build_context
from app.services.intent_router import route_intent
from app.services.memory import list_memories
from app.services.personal_scope import resolve_user_id
from app.services.provider_gateway import request_ai_completion


# Matches context_builder.MAX_NEW_MESSAGE_LENGTH; enforced here too so an
# oversized message is rejected before it is ever saved, instead of being
# saved and then failing when the context builder rejects it.
MAX_MESSAGE_LENGTH = 4_000

DISABLED_REPLY = "AI chat isn't set up yet. Everything else keeps working."
BUDGET_REPLY = (
    "The AI budget for this period is used up right now. "
    "Everything else keeps working."
)
FAILURE_REPLY = "AI didn't respond in time. Please try again in a moment."
MEMORY_WRITE_DECLINE = (
    "I can't save or delete memories from chat yet — use the Memory Center "
    "to manage memories."
)
QUEST_DECLINE = (
    "I can't create or change quests from chat yet — use the Quests page."
)
CLIENT_DECLINE = "I can't act on leads from chat yet — use Client Hunting."
TOOL_DECLINE = "I can't send messages or perform actions from chat yet."
NO_DIRECTION_REPLY = "Do a check-in first so I can suggest a direction."
NO_MEMORIES_REPLY = "You don't have any saved memories yet."


@dataclass(frozen=True)
class ChatTurnResult:
    session_id: int
    user_message: sqlite3.Row
    assistant_message: sqlite3.Row | None
    run: sqlite3.Row
    loop_selected: str
    already_processed: bool


def _deterministic_reply(db: sqlite3.Connection, *, user_id: int, routed) -> str:
    if routed.intent == "show_memories":
        memories = list_memories(db, user_id=user_id)[:10]
        if not memories:
            return NO_MEMORIES_REPLY
        lines = [
            f"- ({memory['memory_type']}) {memory['memory_key']}: {memory['memory_value']}"
            for memory in memories
        ]
        return "Here are your top memories:\n" + "\n".join(lines)

    if routed.intent in {"remember", "forget"}:
        return MEMORY_WRITE_DECLINE

    if routed.intent == "my_level":
        row = db.execute(
            """
            SELECT level, xp_total, xp_into_level, character_class
            FROM game_state
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return "You're level 1 with 0 XP so far."
        return (
            f"You're level {row['level']} ({row['character_class']}), "
            f"{row['xp_total']} XP total, {row['xp_into_level']} XP into "
            "this level."
        )

    if routed.intent == "next_action":
        # Deliberately does not re-invoke choose_direction(): that needs a
        # fresh check-in, active project, and open-quests bundle that this
        # chat turn does not have. Surfacing the last recorded direction is
        # the safe, deterministic equivalent from a bare chat message.
        direction = db.execute(
            """
            SELECT d.main_quest, d.why
            FROM directions AS d
            JOIN checkins AS c ON c.id = d.checkin_id AND c.user_id = d.user_id
            WHERE d.user_id = ?
            ORDER BY d.id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        if direction is None:
            return NO_DIRECTION_REPLY
        return (
            f"Your last suggested direction was: {direction['main_quest']} "
            f"— {direction['why']}"
        )

    if routed.intent == "create_quest":
        return QUEST_DECLINE
    if routed.intent == "review_lead":
        return CLIENT_DECLINE
    if routed.intent == "send_email":
        return TOOL_DECLINE

    raise ValueError(f"No deterministic reply is defined for intent: {routed.intent}")


def _find_message_by_request_key(
    db: sqlite3.Connection,
    *,
    session_id: int,
    user_id: int,
    request_key: str | None,
) -> sqlite3.Row | None:
    if not request_key:
        return None
    return db.execute(
        """
        SELECT * FROM chat_messages
        WHERE session_id = ? AND user_id = ? AND request_key = ?
          AND deleted_at IS NULL
        """,
        (session_id, user_id, request_key),
    ).fetchone()


def send_chat_message(
    db: sqlite3.Connection,
    *,
    session_id: int,
    content: str,
    request_key: str | None = None,
    user_id: int | None = None,
) -> ChatTurnResult:
    """Run one full routine-chat turn through the Phase 8 pipeline.

    Order matches the documented Phase 8 request flow: save the user
    message, create the agent audit run, route the intent deterministically,
    then either answer deterministically or go through the Phase 8.3
    context builder and Phase 8.4 budget/provider gateway, save the
    assistant reply, and finalize the audit run. Every outcome -- including
    disabled AI, exhausted budget, and a provider failure -- finalizes the
    run as 'completed' with a safe fallback reply; none of those are system
    errors.
    """
    safe_user_id = resolve_user_id(db, user_id)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Message is required")
    if len(content.strip()) > MAX_MESSAGE_LENGTH:
        raise ValueError(
            f"Message must be {MAX_MESSAGE_LENGTH} characters or fewer"
        )

    save_result = save_chat_message(
        db,
        session_id=session_id,
        role="user",
        content=content,
        request_key=request_key,
        user_id=safe_user_id,
    )
    user_message = save_result.message

    run_result = create_agent_run(
        db,
        session_id=session_id,
        user_message_id=int(user_message["id"]),
        request_key=request_key,
    )
    run = run_result.run

    assistant_request_key = f"{request_key}:assistant" if request_key else None

    if not run_result.created and run["status"] != "running":
        # A prior attempt with the same request_key already ran this turn
        # to completion (or gave up on it). Never re-run deterministic
        # logic or call the provider again for a retried/duplicate submit.
        assistant_message = _find_message_by_request_key(
            db,
            session_id=session_id,
            user_id=safe_user_id,
            request_key=assistant_request_key,
        )
        return ChatTurnResult(
            session_id=session_id,
            user_message=user_message,
            assistant_message=assistant_message,
            run=run,
            loop_selected=str(run["loop_selected"]),
            already_processed=True,
        )

    routed = route_intent(content)
    run = set_agent_run_context(
        db,
        int(run["id"]),
        intent=routed.intent,
        loop_selected=routed.loop_selected,
    )

    if not routed.needs_model:
        reply_text = _deterministic_reply(db, user_id=safe_user_id, routed=routed)
    else:
        packet = build_context(
            db,
            new_message=content,
            user_id=safe_user_id,
            session_id=session_id,
        )
        step_key = f"{request_key}:ai_call" if request_key else None
        completion = request_ai_completion(
            db,
            run_id=int(run["id"]),
            context_packet=packet,
            step_key=step_key,
        )
        if completion.content is not None:
            reply_text = completion.content
        elif completion.reason == "ai_not_configured":
            reply_text = DISABLED_REPLY
        elif completion.reason == "provider_call_failed":
            reply_text = FAILURE_REPLY
        else:
            reply_text = BUDGET_REPLY

    assistant_save = save_chat_message(
        db,
        session_id=session_id,
        role="assistant",
        content=reply_text,
        request_key=assistant_request_key,
        user_id=safe_user_id,
    )

    run = finalize_agent_run(db, int(run["id"]), status="completed")

    return ChatTurnResult(
        session_id=session_id,
        user_message=user_message,
        assistant_message=assistant_save.message,
        run=run,
        loop_selected=routed.loop_selected,
        already_processed=False,
    )
