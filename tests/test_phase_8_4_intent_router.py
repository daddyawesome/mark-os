from __future__ import annotations

import pytest

from app.services.intent_router import (
    LOOP_CLIENT_HUNTING,
    LOOP_DATA_LOOKUP,
    LOOP_DIRECTOR_COACH,
    LOOP_MEMORY_MANAGEMENT,
    LOOP_QUEST_PLANNING,
    LOOP_ROUTINE_CHAT,
    LOOP_TOOL_ACTION,
    route_intent,
)


@pytest.mark.parametrize(
    "message, expected_loop",
    [
        ("remember that I prefer mornings", LOOP_MEMORY_MANAGEMENT),
        ("forget the old work schedule note", LOOP_MEMORY_MANAGEMENT),
        ("please show my memories", LOOP_MEMORY_MANAGEMENT),
        ("what should I do next?", LOOP_DIRECTOR_COACH),
        ("create a quest to refactor the login page", LOOP_QUEST_PLANNING),
        ("can you review this lead for me", LOOP_CLIENT_HUNTING),
        ("what is my level right now", LOOP_DATA_LOOKUP),
        ("send an email to the client", LOOP_TOOL_ACTION),
    ],
)
def test_deterministic_examples_never_need_a_model(message, expected_loop):
    routed = route_intent(message)
    assert routed.loop_selected == expected_loop
    assert routed.needs_model is False


def test_unmatched_message_falls_through_to_routine_chat():
    routed = route_intent("How was the weather during the Apollo 11 launch?")
    assert routed.loop_selected == LOOP_ROUTINE_CHAT
    assert routed.needs_model is True
    assert routed.intent == "general_chat"


def test_matching_is_case_insensitive_and_ignores_surrounding_text():
    routed = route_intent("   REMEMBER that Fridays are for deep work.")
    assert routed.loop_selected == LOOP_MEMORY_MANAGEMENT


def test_blank_message_is_rejected():
    with pytest.raises(ValueError):
        route_intent("   ")
