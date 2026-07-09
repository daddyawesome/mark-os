from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass(frozen=True)
class Direction:
    main_quest: str
    why: str
    side_quest_1: str
    side_quest_2: str
    avoid: str
    signal: str


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(term in lowered for term in terms)


def choose_direction(
    checkin: Mapping[str, object],
    active_project: Optional[Mapping[str, object]],
    previous_cash: Optional[float] = None,
) -> Direction:
    cash = float(checkin.get("cash") or 0)
    expenses = float(checkin.get("expenses") or 0)
    free_hours = float(checkin.get("free_hours") or 0)
    energy = int(checkin.get("energy") or 3)
    blocker = str(checkin.get("blocker") or "")
    accomplished = str(checkin.get("accomplished") or "")

    cash_drop = previous_cash is not None and cash > 0 and cash < previous_cash
    severe_cash_pressure = 0 < cash < 10_000
    lead_blocker = _contains(blocker, ("lead", "client", "customer", "outreach", "job search"))
    urgent_blocker = _contains(blocker, ("urgent", "deadline", "production", "broken", "incident", "bank"))
    low_capacity = free_hours < 1 or energy <= 2

    project_name = active_project.get("name") if active_project else "your highest-priority project"
    next_action = (
        active_project.get("next_action")
        if active_project
        else "Choose one concrete deliverable and complete it before starting anything else."
    )

    if urgent_blocker:
        return Direction(
            main_quest=f"Remove the urgent blocker first: {blocker.strip() or 'resolve the immediate deadline risk'}",
            why="Urgent unresolved problems can erase the value of every other task. Stabilize reality before optimizing it.",
            side_quest_1="Write the exact next physical action required to resolve the blocker.",
            side_quest_2="After it is stable, record what caused it so MARK OS can spot the pattern earlier.",
            avoid="Do not start a new feature or new opportunity until the urgent issue is contained.",
            signal="stability-first",
        )

    if severe_cash_pressure:
        return Direction(
            main_quest="Create one near-term income opportunity today: contact or apply to one qualified buyer with a real data problem.",
            why="Cash pressure changes the priority order. Revenue-producing actions come before polish and experimentation.",
            side_quest_1="Use one pain-intent search and save the best qualified lead.",
            side_quest_2=f"Spend any remaining focused time on {project_name}, but only after the income action is complete.",
            avoid="Do not spend money on tools, courses, ads, or subscriptions today.",
            signal="cash-protection",
        )

    if low_capacity:
        return Direction(
            main_quest=f"Complete the smallest shippable step for {project_name}: {next_action}",
            why="Your available capacity is limited today. A small finished step keeps momentum without pretending you have a full work session.",
            side_quest_1="Write tomorrow's first action before stopping.",
            side_quest_2="Capture one sentence about what reduced your time or energy today.",
            avoid="Do not compensate for low capacity by opening several new tasks.",
            signal="minimum-viable-progress",
        )

    if lead_blocker and not accomplished.strip():
        return Direction(
            main_quest="Find one qualified person or company currently showing a real reporting, Excel, Power BI, SQL, or automation pain—and send one tailored message.",
            why="Your repeated blocker is lead discovery. One qualified conversation is more valuable than another round of broad searching or profile editing.",
            side_quest_1="Search using pain-intent or hiring-intent language, not broad terms like 'Power BI help'.",
            side_quest_2=f"After outreach, complete one visible step in {project_name}.",
            avoid="Do not spend the session rewriting your CV or browsing generic training posts.",
            signal="revenue-pipeline",
        )

    if cash_drop and expenses > 0:
        return Direction(
            main_quest=f"Ship the next visible step in {project_name}: {next_action}",
            why="Cash moved downward, but there is no emergency signal. Protect spending while continuing to build an asset that strengthens your earning power.",
            side_quest_1="Record what today's spending was for and whether it was planned.",
            side_quest_2="Do one 20-minute qualified-lead search after the project step is shipped.",
            avoid="Do not buy a new tool to solve a problem the current stack can already handle.",
            signal="build-with-cash-discipline",
        )

    return Direction(
        main_quest=f"Ship the next visible step in {project_name}: {next_action}",
        why="You have enough capacity and no stronger emergency signal. Shipping the flagship product creates portfolio proof, product skill, and a potential business asset at the same time.",
        side_quest_1="Find one qualified lead using a pain-intent or hiring-intent search.",
        side_quest_2="End the session with a short check-in so tomorrow's recommendation uses real evidence.",
        avoid="Do not redesign, add integrations, or start another project before this step works.",
        signal="highest-leverage-build",
    )
