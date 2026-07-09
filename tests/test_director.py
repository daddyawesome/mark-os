from app.services.director import choose_direction


def project():
    return {
        "name": "MARK OS v0.1",
        "next_action": "Submit the first real check-in.",
    }


def test_low_capacity_creates_small_quest():
    result = choose_direction(
        {
            "cash": 30_000,
            "expenses": 0,
            "free_hours": 0.5,
            "energy": 2,
            "accomplished": "",
            "blocker": "",
        },
        project(),
    )
    assert result.signal == "minimum-viable-progress"


def test_cash_pressure_prioritizes_income():
    result = choose_direction(
        {
            "cash": 8_000,
            "expenses": 0,
            "free_hours": 2,
            "energy": 4,
            "accomplished": "",
            "blocker": "",
        },
        project(),
    )
    assert result.signal == "cash-protection"


def test_default_prioritizes_flagship_build():
    result = choose_direction(
        {
            "cash": 30_000,
            "expenses": 0,
            "free_hours": 2,
            "energy": 4,
            "accomplished": "worked on project",
            "blocker": "",
        },
        project(),
    )
    assert result.signal == "highest-leverage-build"
    assert "MARK OS v0.1" in result.main_quest
