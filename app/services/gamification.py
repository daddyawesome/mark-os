from __future__ import annotations

from dataclasses import dataclass

XP_BY_DIFFICULTY = {
    "quick": 10,
    "normal": 25,
    "hard": 50,
    "epic": 100,
}


@dataclass(frozen=True)
class XPAwardResult:
    level: int
    xp_total: int
    xp_into_level: int
    levels_gained: int


def normalize_difficulty(value: str) -> str:
    difficulty = (value or "normal").strip().lower()
    return difficulty if difficulty in XP_BY_DIFFICULTY else "normal"


def xp_for_difficulty(difficulty: str) -> int:
    return XP_BY_DIFFICULTY[normalize_difficulty(difficulty)]


def _xp_required_for_next_level(level: int) -> int:
    """Internal level curve. Thresholds are intentionally not exposed in the UI."""
    safe_level = max(1, int(level))
    return 100 + (safe_level * 25)


def apply_xp(
    *,
    level: int,
    xp_total: int | None,
    xp_into_level: int,
    awarded_xp: int,
) -> XPAwardResult:
    current_level = max(1, int(level))
    total = max(0, int(xp_total or 0))
    progress = max(0, int(xp_into_level or 0))
    award = max(0, int(awarded_xp))

    total += award
    progress += award
    levels_gained = 0

    while progress >= _xp_required_for_next_level(current_level):
        progress -= _xp_required_for_next_level(current_level)
        current_level += 1
        levels_gained += 1

    return XPAwardResult(
        level=current_level,
        xp_total=total,
        xp_into_level=progress,
        levels_gained=levels_gained,
    )
