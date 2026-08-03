from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


# MARK OS v0.x is a single-user tool whose cash check-ins are recorded in PHP.
# Keep this injectable so a future multi-profile/currency version can load the
# policy from profile settings instead of sharing one financial assumption.
DEFAULT_SEVERE_CASH_PRESSURE_THRESHOLD_PHP = 10_000.0

# Keep deterministic matching narrow and high-signal. Prefer structured
# blocker/quest tags—or the future classification stage—to adding broad words
# whose meaning depends on context.
URGENT_BLOCKER_TERMS = (
    "urgent blocker",
    "urgent issue",
    "urgent incident",
    "urgent outage",
    "deadline today",
    "deadline tomorrow",
    "deadline missed",
    "missed deadline",
    "overdue deadline",
    "production outage",
    "production incident",
    "production down",
    "production is down",
    "production is broken",
    "service outage",
    "service down",
    "service is down",
    "system down",
    "system is down",
    "system is broken",
    "site down",
    "site is down",
    "site is broken",
    "account locked",
    "account is locked",
    "account frozen",
    "account is frozen",
    "bank transfer blocked",
)

NON_URGENT_CONTEXT_TERMS = (
    "no urgent blocker",
    "no urgent issue",
    "nothing urgent",
    "not urgent",
    "deadline met",
    "deadline was met",
    "met the deadline",
    "deadline complete",
    "deadline completed",
    "incident resolved",
    "resolved incident",
    "resolved",
)

LEAD_BLOCKER_TERMS = (
    "no leads",
    "no qualified leads",
    "need leads",
    "need qualified leads",
    "find leads",
    "finding leads",
    "qualified lead",
    "qualified leads",
    "qualified client",
    "qualified clients",
    "need clients",
    "find clients",
    "finding clients",
    "need customers",
    "find customers",
    "finding customers",
    "client acquisition",
    "customer acquisition",
    "sales outreach",
    "job search",
)

INCOME_QUEST_TERMS = (
    "qualified lead",
    "qualified leads",
    "qualified client",
    "qualified clients",
    "qualified customer",
    "qualified customers",
    "qualified buyer",
    "qualified buyers",
    "client outreach",
    "customer outreach",
    "buyer outreach",
    "sales outreach",
    "client acquisition",
    "customer acquisition",
    "income opportunity",
    "generate income",
    "increase income",
    "generate revenue",
    "revenue opportunity",
    "job application",
    "job applications",
    "job search",
)

# These are transparent, hand-tuned v0.x heuristics—not learned weights. Once
# MARK OS records whether recommendations were followed and useful, calibrate
# them against that evidence instead of continuing to tune them by feel.
QUEST_PRIORITY_WEIGHT = 10
QUEST_TIME_FIT_BONUS = 20
QUEST_TIME_MISMATCH_PENALTY = 8
QUEST_ENERGY_FIT_BONUS = 8
QUEST_ENERGY_MISMATCH_PENALTY = 6
ACTIVE_QUEST_BONUS = 6
INCOME_ALIGNMENT_BONUS = 30

_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_CLAUSE_SPLIT_PATTERN = re.compile(
    r"(?:[.;!?\n]+|\b(?:and|but|however|although|yet)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Direction:
    main_quest: str
    why: str
    side_quest_1: str
    side_quest_2: str
    avoid: str
    signal: str


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    """Match complete words or phrases, never arbitrary substrings."""
    normalized_text = " ".join(_WORD_PATTERN.findall((text or "").casefold()))
    if not normalized_text:
        return False

    padded_text = f" {normalized_text} "
    for term in terms:
        normalized_term = " ".join(_WORD_PATTERN.findall(term.casefold()))
        if normalized_term and f" {normalized_term} " in padded_text:
            return True
    return False


def _has_urgent_blocker(text: str) -> bool:
    """Require urgency and its negation/resolution to occur in one clause."""
    clauses = _CLAUSE_SPLIT_PATTERN.split(text or "")
    return any(
        _contains(clause, URGENT_BLOCKER_TERMS)
        and not _contains(clause, NON_URGENT_CONTEXT_TERMS)
        for clause in clauses
    )


def _best_fitting_quest(
    open_quests: Sequence[Mapping[str, object]] | None,
    *,
    free_hours: float,
    energy: int,
    prefer_income: bool = False,
    require_capacity_fit: bool = False,
) -> Mapping[str, object] | None:
    if not open_quests:
        return None

    available_minutes = max(0, int(free_hours * 60))
    scored: list[tuple[float, Mapping[str, object]]] = []
    for quest in open_quests:
        if str(quest.get("status") or "").lower() in {"completed", "abandoned"}:
            continue
        estimated = int(quest.get("estimated_minutes") or 30)
        priority = float(quest.get("effective_priority") or quest.get("priority") or 5)
        energy_required = int(quest.get("energy_required") or 3)
        if require_capacity_fit and (
            not available_minutes
            or estimated > available_minutes
            or energy_required > energy
        ):
            continue
        title = str(quest.get("title") or "")
        description = str(quest.get("description") or "")
        goal_title = str(quest.get("goal_title") or "")
        income_signal = _contains(
            f"{title} {description} {goal_title}",
            INCOME_QUEST_TERMS,
        )

        score = priority * QUEST_PRIORITY_WEIGHT
        if available_minutes and estimated <= available_minutes:
            score += QUEST_TIME_FIT_BONUS
        else:
            score -= QUEST_TIME_MISMATCH_PENALTY
        if energy_required <= energy:
            score += QUEST_ENERGY_FIT_BONUS
        else:
            score -= QUEST_ENERGY_MISMATCH_PENALTY
        if str(quest.get("status")) == "active":
            score += ACTIVE_QUEST_BONUS
        if prefer_income and income_signal:
            score += INCOME_ALIGNMENT_BONUS
        scored.append((score, quest))

    if not scored:
        return None
    return sorted(scored, key=lambda item: item[0], reverse=True)[0][1]


def _quest_text(quest: Mapping[str, object]) -> str:
    title = str(quest.get("title") or "selected quest")
    minutes = quest.get("estimated_minutes")
    xp = quest.get("xp_reward")
    meta = []
    if minutes:
        meta.append(f"~{minutes} min")
    if xp:
        meta.append(f"+{xp} XP")
    suffix = f" ({', '.join(meta)})" if meta else ""
    return f"Open and complete quest: {title}{suffix}"


def _low_capacity_fallback(
    *,
    project_name: object,
    next_action: object,
    free_hours: float,
) -> str:
    available_minutes = max(0, int(free_hours * 60))
    if not available_minutes:
        return (
            f"Define the smallest next step for {project_name}; do not begin the "
            f"full action yet: {next_action}"
        )

    timebox_minutes = min(30, available_minutes)
    return (
        f"Spend no more than {timebox_minutes} minutes on one small slice of "
        f"{project_name}; do not try to finish the full action: {next_action}"
    )


def choose_direction(
    checkin: Mapping[str, object],
    active_project: Optional[Mapping[str, object]],
    previous_cash: Optional[float] = None,
    open_quests: Sequence[Mapping[str, object]] | None = None,
    *,
    severe_cash_pressure_threshold: float = DEFAULT_SEVERE_CASH_PRESSURE_THRESHOLD_PHP,
) -> Direction:
    """Choose one direction using explicit, deterministic v0.x policy rules."""
    raw_cash = checkin.get("cash")
    cash = (
        None
        if raw_cash is None or not str(raw_cash).strip()
        else float(raw_cash)
    )
    expenses = float(checkin.get("expenses") or 0)
    free_hours = float(checkin.get("free_hours") or 0)
    energy = int(checkin.get("energy") or 3)
    blocker = str(checkin.get("blocker") or "")
    accomplished = str(checkin.get("accomplished") or "")

    cash_drop = (
        previous_cash is not None
        and cash is not None
        and cash > 0
        and cash < previous_cash
    )
    severe_cash_pressure = (
        cash is not None and cash < severe_cash_pressure_threshold
    )
    lead_blocker = _contains(blocker, LEAD_BLOCKER_TERMS)
    urgent_blocker = _has_urgent_blocker(blocker)
    low_capacity = free_hours < 1 or energy <= 2
    project_name = active_project.get("name") if active_project else "your highest-priority project"
    next_action = (
        active_project.get("next_action")
        if active_project
        else "Choose one concrete deliverable and complete it before starting anything else."
    )

    # Deliberate branch priority: stabilize a true urgent incident first, then
    # respect the user's actual capacity, then protect cash. A burnt-out user
    # gets a viable action rather than an unrealistic income directive.
    if urgent_blocker:
        return Direction(
            main_quest=f"Remove the urgent blocker first: {blocker.strip() or 'resolve the immediate deadline risk'}",
            why="Urgent unresolved problems can erase the value of every other task. Stabilize reality before optimizing it.",
            side_quest_1="Write the exact next physical action required to resolve the blocker.",
            side_quest_2="After it is stable, record what caused it so MARK OS can spot the pattern earlier.",
            avoid="Do not start a new feature or new opportunity until the urgent issue is contained.",
            signal="stability-first",
        )

    if low_capacity:
        small_quest = _best_fitting_quest(
            open_quests,
            free_hours=free_hours,
            energy=energy,
            require_capacity_fit=True,
        )
        return Direction(
            main_quest=(
                _quest_text(small_quest)
                if small_quest
                else _low_capacity_fallback(
                    project_name=project_name,
                    next_action=next_action,
                    free_hours=free_hours,
                )
            ),
            why="Your available capacity is limited today. A small finished step keeps momentum without pretending you have a full work session.",
            side_quest_1="Write tomorrow's first action before stopping.",
            side_quest_2="Capture one sentence about what reduced your time or energy today.",
            avoid="Do not compensate for low capacity by opening several new tasks.",
            signal="minimum-viable-progress",
        )

    if severe_cash_pressure:
        income_quest = _best_fitting_quest(
            open_quests,
            free_hours=free_hours,
            energy=energy,
            prefer_income=True,
        )
        return Direction(
            main_quest=_quest_text(income_quest) if income_quest else "Create one near-term income opportunity today: contact or apply to one qualified buyer with a real data problem.",
            why="Cash pressure changes the priority order. Revenue-producing actions come before polish and experimentation.",
            side_quest_1="Use one pain-intent search and save the best qualified lead.",
            side_quest_2=f"Spend any remaining focused time on {project_name}, but only after the income action is complete.",
            avoid="Do not spend money on tools, courses, ads, or subscriptions today.",
            signal="cash-protection",
        )

    if lead_blocker and not accomplished.strip():
        income_quest = _best_fitting_quest(
            open_quests,
            free_hours=free_hours,
            energy=energy,
            prefer_income=True,
        )
        return Direction(
            main_quest=_quest_text(income_quest) if income_quest else "Find one qualified person or company currently showing a real reporting, Excel, Power BI, SQL, or automation pain—and send one tailored message.",
            why="Your repeated blocker is lead discovery. One qualified conversation is more valuable than another round of broad searching or profile editing.",
            side_quest_1="Search using pain-intent or hiring-intent language, not broad terms like 'Power BI help'.",
            side_quest_2=f"After outreach, complete one visible step in {project_name}.",
            avoid="Do not spend the session rewriting your CV or browsing generic training posts.",
            signal="revenue-pipeline",
        )

    if cash_drop and expenses > 0:
        build_quest = _best_fitting_quest(open_quests, free_hours=free_hours, energy=energy)
        return Direction(
            main_quest=_quest_text(build_quest) if build_quest else f"Ship the next visible step in {project_name}: {next_action}",
            why="Cash moved downward, but there is no emergency signal. Protect spending while continuing to build an asset that strengthens your earning power.",
            side_quest_1="Record what today's spending was for and whether it was planned.",
            side_quest_2="Do one 20-minute qualified-lead search after the project step is shipped.",
            avoid="Do not buy a new tool to solve a problem the current stack can already handle.",
            signal="build-with-cash-discipline",
        )

    build_quest = _best_fitting_quest(open_quests, free_hours=free_hours, energy=energy)
    return Direction(
        main_quest=_quest_text(build_quest) if build_quest else f"Ship the next visible step in {project_name}: {next_action}",
        why="You have enough capacity and no stronger emergency signal. Shipping the flagship product creates portfolio proof, product skill, and a potential business asset at the same time.",
        side_quest_1="Find one qualified lead using a pain-intent or hiring-intent search.",
        side_quest_2="End the session with a short check-in so tomorrow's recommendation uses real evidence.",
        avoid="Do not redesign, add integrations, or start another project before this step works.",
        signal="highest-leverage-build",
    )
