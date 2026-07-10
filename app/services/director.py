from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Direction:
    main_quest: str
    why: str
    side_quest_1: str
    side_quest_2: str
    avoid: str
    signal: str


def choose_direction(
    checkin: dict[str, Any],
    project: dict[str, Any] | None,
    previous_cash: float | None = None,
) -> Direction:
    """
    Generate the next recommended direction from the user's latest check-in.

    This is intentionally rule-based for now.
    Later, we can replace or enhance this with the budget-safe AI architecture.
    """

    cash = checkin.get("cash")
    expenses = checkin.get("expenses") or 0
    free_hours = checkin.get("free_hours") or 0
    energy = checkin.get("energy") or 3
    blocker = (checkin.get("blocker") or "").strip()
    accomplished = (checkin.get("accomplished") or "").strip()

    project_name = "your highest-priority active project"

    if project:
        project_name = (
            project.get("name")
            or project.get("title")
            or project.get("project_name")
            or project_name
        )

    # Low-energy day
    if energy <= 2:
        return Direction(
            main_quest=f"Spend 25 focused minutes moving {project_name} forward.",
            why=(
                "Your energy is low, so the goal is to preserve momentum "
                "without creating burnout."
            ),
            side_quest_1="Remove one small blocker.",
            side_quest_2="Write down the exact next step for tomorrow.",
            avoid="Starting a large new project.",
            signal="A small but real task is completed.",
        )

    # Little available time
    if free_hours < 1:
        return Direction(
            main_quest=f"Complete one small, visible task for {project_name}.",
            why=(
                "You have limited time today, so finishing one concrete action "
                "is more valuable than planning many tasks."
            ),
            side_quest_1="Spend 10 minutes clearing the biggest blocker.",
            side_quest_2="Prepare tomorrow's first task.",
            avoid="Research without a clear output.",
            signal="One item moves from planned to completed.",
        )

    # Active blocker
    if blocker:
        return Direction(
            main_quest=f"Resolve or reduce this blocker: {blocker}",
            why=(
                "The blocker is currently limiting progress. Removing friction "
                "will make future work faster."
            ),
            side_quest_1=f"Spend the remaining time advancing {project_name}.",
            side_quest_2="Document what solved the blocker.",
            avoid="Ignoring the blocker and adding more work.",
            signal="The blocker is removed or reduced to a specific next action.",
        )

    # Cash decreased
    if (
        cash is not None
        and previous_cash is not None
        and cash < previous_cash
    ):
        cash_change = previous_cash - cash

        return Direction(
            main_quest=(
                f"Create one income-producing action for {project_name}."
            ),
            why=(
                f"Cash decreased by {cash_change:,.2f}. "
                "Today's priority should include an action that can lead to income."
            ),
            side_quest_1="Review today's spending for avoidable expenses.",
            side_quest_2="Send one application, proposal, or outreach message.",
            avoid="Spending the entire work session on non-revenue features.",
            signal="One real opportunity is created or advanced.",
        )

    # Productive momentum
    if accomplished:
        return Direction(
            main_quest=f"Build on yesterday's momentum by advancing {project_name}.",
            why=(
                f"You already completed: {accomplished}. "
                "Continuing momentum is easier than restarting."
            ),
            side_quest_1="Finish one measurable deliverable.",
            side_quest_2="Record what changed after completion.",
            avoid="Switching to a new project before finishing the current step.",
            signal="A visible deliverable exists by the end of the session.",
        )

    # Default
    return Direction(
        main_quest=f"Complete the highest-leverage next step for {project_name}.",
        why=(
            "Focused execution on one important project creates more progress "
            "than spreading effort across many tasks."
        ),
        side_quest_1="Complete one supporting task.",
        side_quest_2="Prepare the exact next action for the next work session.",
        avoid="Starting unrelated work.",
        signal="One meaningful project milestone moves forward.",
    )