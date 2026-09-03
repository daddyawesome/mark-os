from __future__ import annotations

import re
from dataclasses import dataclass


# Deterministic loop names. These are the eight controlled AI loops named in
# the Phase 8 architecture; "none" is not a loop, it means no model call is
# needed at all.
LOOP_NONE = "none"
LOOP_MEMORY_MANAGEMENT = "memory_management"
LOOP_DIRECTOR_COACH = "director_coach"
LOOP_QUEST_PLANNING = "quest_planning"
LOOP_CLIENT_HUNTING = "client_hunting"
LOOP_DATA_LOOKUP = "data_lookup"
LOOP_TOOL_ACTION = "tool_action"
LOOP_ROUTINE_CHAT = "routine_chat"


@dataclass(frozen=True)
class RoutedIntent:
    intent: str
    loop_selected: str
    needs_model: bool


# Ordered, deterministic examples straight from the Phase 8 intent-routing
# specification. Patterns are checked in order; the first match wins. A
# message that matches nothing here falls through to routine_chat, which is
# the only path that ever reaches the AI gateway.
_DETERMINISTIC_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"^\s*remember\b", re.IGNORECASE), "remember", LOOP_MEMORY_MANAGEMENT),
    (re.compile(r"^\s*forget\b", re.IGNORECASE), "forget", LOOP_MEMORY_MANAGEMENT),
    (
        re.compile(r"\bshow (?:me )?my memories\b", re.IGNORECASE),
        "show_memories",
        LOOP_MEMORY_MANAGEMENT,
    ),
    (
        re.compile(r"\bwhat should i do next\b", re.IGNORECASE),
        "next_action",
        LOOP_DIRECTOR_COACH,
    ),
    (
        re.compile(r"^\s*create a quest\b", re.IGNORECASE),
        "create_quest",
        LOOP_QUEST_PLANNING,
    ),
    (
        re.compile(r"\breview this lead\b", re.IGNORECASE),
        "review_lead",
        LOOP_CLIENT_HUNTING,
    ),
    (
        re.compile(r"\bwhat is my level\b", re.IGNORECASE),
        "my_level",
        LOOP_DATA_LOOKUP,
    ),
    (
        re.compile(r"^\s*send an email\b", re.IGNORECASE),
        "send_email",
        LOOP_TOOL_ACTION,
    ),
)


def route_intent(message: str) -> RoutedIntent:
    """Classify one user message using deterministic checks only.

    No model call happens here. A match returns `needs_model=False`; the
    caller should handle that loop with existing services and never reach
    the AI gateway for it. Only an unmatched message is routed to
    `routine_chat`, which is the sole path allowed to call a paid provider.
    """
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Message is required")

    for pattern, intent, loop in _DETERMINISTIC_PATTERNS:
        if pattern.search(message):
            return RoutedIntent(intent=intent, loop_selected=loop, needs_model=False)

    return RoutedIntent(
        intent="general_chat",
        loop_selected=LOOP_ROUTINE_CHAT,
        needs_model=True,
    )
