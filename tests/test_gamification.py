from app.services.gamification import apply_xp, xp_for_difficulty


def test_quest_difficulty_rewards():
    assert xp_for_difficulty("quick") == 10
    assert xp_for_difficulty("normal") == 25
    assert xp_for_difficulty("hard") == 50
    assert xp_for_difficulty("epic") == 100
    assert xp_for_difficulty("unknown") == 25


def test_xp_accumulates_without_forcing_level_up():
    result = apply_xp(
        level=3,
        xp_total=None,
        xp_into_level=0,
        awarded_xp=25,
    )
    assert result.level == 3
    assert result.xp_total == 25
    assert result.xp_into_level == 25
    assert result.levels_gained == 0


def test_large_award_can_level_up():
    result = apply_xp(
        level=3,
        xp_total=0,
        xp_into_level=0,
        awarded_xp=500,
    )
    assert result.level > 3
    assert result.xp_total == 500
    assert result.levels_gained >= 1
