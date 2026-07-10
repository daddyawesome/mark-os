from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

# --- Tuning constants -------------------------------------------------

STATUS_WEIGHT = {"active": 6, "backlog": 0}

DIFFICULTY_ENERGY_FIT = {"quick": 1, "normal": 2, "hard": 3, "epic": 4}

INCOME_KEYWORDS = (
    "lead", "client", "outreach", "revenue", "income", "sale", "sales",
    "customer", "pitch", "proposal", "invoice", "pricing", "buyer",
)

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "for", "is", "on", "in",
    "with", "my", "i", "it", "this", "that", "be", "at", "as", "not",
}


@dataclass
class Direction:
    main_quest: str
    why: str
    side_quest_1: str
    side_quest_2: str
    avoid: str
    signal: str
    main_quest_id: int | None = None
    side_quest_1_id: int | None = None
    side_quest_2_id: int | None = None


def _tokenize(text: str) -> set[str]:
    cleaned_words = set()
    for word in (text or "").split():
        cleaned = word.strip(".,:;!?()").lower()
        if cleaned not in STOPWORDS and len(cleaned) > 2:
            cleaned_words.add(cleaned)
    return cleaned_words


def _score_quest(
    quest: dict[str, Any],
    checkin: dict[str, Any],
    previous_cash: float | None,
) -> tuple[float, list[str]]:
    """Score one open quest against today's real conditions. Higher = better fit."""
    reasons: list[str] = []
    score = 0.0

    priority = quest.get("effective_priority")
    if priority is None:
        priority = quest.get("priority") or 5
    score += priority * 2

    if quest.get("goal_title") and quest.get("effective_priority", 0) > (quest.get("priority") or 5):
        reasons.append(f"supports the goal: {quest['goal_title']}")

    status = (quest.get("status") or "backlog").lower()
    score += STATUS_WEIGHT.get(status, 0)
    if status == "active":
        reasons.append("already in progress")

    energy = checkin.get("energy") or 3
    free_hours = checkin.get("free_hours") or 0
    difficulty = (quest.get("difficulty") or "normal").lower()
    difficulty_fit = DIFFICULTY_ENERGY_FIT.get(difficulty, 2)

    if energy <= 2 and difficulty_fit <= 1:
        score += 4
        reasons.append("matches today's low energy")
    elif energy >= 4 and difficulty_fit >= 3:
        score += 4
        reasons.append("matches today's high energy")
    elif energy <= 2 and difficulty_fit >= 3:
        score -= 14
        reasons.append("heavier than today's energy allows")

    est_minutes = quest.get("estimated_minutes")
    if est_minutes and free_hours:
        if est_minutes <= free_hours * 60:
            score += 3
            reasons.append("fits available time")
        else:
            score -= 5
            reasons.append("longer than today's available time")

    blocker = (checkin.get("blocker") or "").strip()
    if blocker:
        blocker_words = _tokenize(blocker)
        quest_words = _tokenize(f"{quest.get('title', '')} {quest.get('description', '')}")
        if blocker_words & quest_words:
            score += 8
            reasons.append("directly addresses today's blocker")

    cash = checkin.get("cash")
    if cash is not None and previous_cash is not None and cash < previous_cash:
        quest_text = f"{quest.get('title', '')} {quest.get('description', '')}".lower()
        if any(keyword in quest_text for keyword in INCOME_KEYWORDS):
            score += 7
            reasons.append("cash is down and this quest can create income")

    xp_reward = quest.get("xp_reward") or 0
    score += xp_reward / 40  # small tie-breaker nudge toward higher-value quests

    due_date = quest.get("due_date")
    if due_date:
        score += 2
        reasons.append("has a due date")

    return score, reasons


def _fallback_direction(
    checkin: dict[str, Any],
    project: dict[str, Any] | None,
    previous_cash: float | None,
) -> Direction:
    """Used only when there are no open quests to score yet."""
    cash = checkin.get("cash")
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

    if energy <= 2:
        return Direction(
            main_quest=f"Spend 25 focused minutes moving {project_name} forward.",
            why="Your energy is low, so the goal is to preserve momentum without burnout.",
            side_quest_1="Remove one small blocker.",
            side_quest_2="Write down the exact next step for tomorrow.",
            avoid="Starting a large new project.",
            signal="low-energy-preservation",
        )

    if free_hours < 1:
        return Direction(
            main_quest=f"Complete one small, visible task for {project_name}.",
            why="Limited time today, so one finished action beats many planned ones.",
            side_quest_1="Spend 10 minutes clearing the biggest blocker.",
            side_quest_2="Prepare tomorrow's first task.",
            avoid="Research without a clear output.",
            signal="time-constrained",
        )

    if blocker:
        return Direction(
            main_quest=f"Resolve or reduce this blocker: {blocker}",
            why="The blocker is limiting progress. Removing friction speeds up everything after it.",
            side_quest_1=f"Spend the remaining time advancing {project_name}.",
            side_quest_2="Document what solved the blocker.",
            avoid="Ignoring the blocker and adding more work.",
            signal="blocker-removal",
        )

    if cash is not None and previous_cash is not None and cash < previous_cash:
        cash_change = previous_cash - cash
        return Direction(
            main_quest=f"Create one income-producing action for {project_name}.",
            why=f"Cash decreased by {cash_change:,.2f}. Today should include a revenue action.",
            side_quest_1="Review today's spending for avoidable expenses.",
            side_quest_2="Send one application, proposal, or outreach message.",
            avoid="Spending the entire session on non-revenue work.",
            signal="cash-declining",
        )

    if accomplished:
        return Direction(
            main_quest=f"Build on yesterday's momentum by advancing {project_name}.",
            why=f"You already completed: {accomplished}. Continuing is easier than restarting.",
            side_quest_1="Finish one measurable deliverable.",
            side_quest_2="Record what changed after completion.",
            avoid="Switching to a new project before finishing this step.",
            signal="momentum",
        )

    return Direction(
        main_quest=f"Complete the highest-leverage next step for {project_name}.",
        why="Focused execution on one important project beats spreading effort thin.",
        side_quest_1="Complete one supporting task.",
        side_quest_2="Prepare the exact next action for the next session.",
        avoid="Starting unrelated work.",
        signal="default-focus",
    )


def choose_direction(
    checkin: dict[str, Any],
    project: dict[str, Any] | None,
    previous_cash: float | None = None,
    open_quests: Iterable[dict[str, Any]] | None = None,
) -> Direction:
    """
    Score every real open quest against today's check-in and pick:
    one Main Quest, two Side Quests, and one thing to avoid.

    Falls back to the original rule-based direction only when there is
    nothing real to choose from yet.
    """
    candidates = [
        q for q in (open_quests or []) if (q.get("status") or "backlog") != "completed"
    ]

    if not candidates:
        return _fallback_direction(checkin, project, previous_cash)

    scored = sorted(
        (
            (_score_quest(quest, checkin, previous_cash), quest)
            for quest in candidates
        ),
        key=lambda pair: pair[0][0],
        reverse=True,
    )

    (top_score, top_reasons), main_quest = scored[0]
    side_picks = scored[1:3]

    energy = checkin.get("energy") or 3
    blocker = (checkin.get("blocker") or "").strip()

    why_parts = []
    if top_reasons:
        why_parts.append("Chosen because it " + ", ".join(top_reasons) + ".")
    else:
        why_parts.append("Chosen as the highest-leverage open quest available today.")
    if energy <= 2:
        why_parts.append("Energy is low today — avoid stacking more hard quests on top of this.")
    if blocker and "directly addresses today's blocker" not in top_reasons:
        why_parts.append(f"Current blocker to keep in mind: {blocker}.")

    def _title(pick):
        return pick[1]["title"] if pick else None

    side_quest_1 = _title(side_picks[0]) if len(side_picks) > 0 else "Log a short reflection on today's progress."
    side_quest_2 = _title(side_picks[1]) if len(side_picks) > 1 else "Prepare tomorrow's first action."

    negative_candidates = [quest for (score, _), quest in scored if score < 0]
    if negative_candidates:
        avoid = f'Starting "{negative_candidates[0]["title"]}" today — it does not fit your current time or energy.'
    elif energy <= 2:
        avoid = "Starting a new large or unfamiliar quest."
    else:
        avoid = "Switching quests before finishing the one you started."

    return Direction(
        main_quest=main_quest["title"],
        why=" ".join(why_parts),
        side_quest_1=side_quest_1,
        side_quest_2=side_quest_2,
        avoid=avoid,
        signal="quest-scored",
        main_quest_id=main_quest.get("id"),
        side_quest_1_id=side_picks[0][1].get("id") if len(side_picks) > 0 else None,
        side_quest_2_id=side_picks[1][1].get("id") if len(side_picks) > 1 else None,
    )