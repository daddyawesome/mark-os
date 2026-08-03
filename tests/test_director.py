import pytest

from app.services.director import _best_fitting_quest, choose_direction


PROJECT = {
    "name": "MARK OS",
    "next_action": "Ship the next tested increment.",
}


def checkin(**overrides):
    values = {
        "cash": 20_000,
        "expenses": 0,
        "free_hours": 3,
        "energy": 4,
        "accomplished": "",
        "blocker": "",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("overrides", "previous_cash", "expected_signal"),
    [
        pytest.param(
            {"blocker": "A production incident is blocking deployment"},
            None,
            "stability-first",
            id="urgent-blocker",
        ),
        pytest.param(
            {"cash": 9_999},
            None,
            "cash-protection",
            id="severe-cash-pressure",
        ),
        pytest.param(
            {"free_hours": 0.5},
            None,
            "minimum-viable-progress",
            id="low-capacity",
        ),
        pytest.param(
            {"blocker": "No qualified leads yet"},
            None,
            "revenue-pipeline",
            id="lead-blocker",
        ),
        pytest.param(
            {"cash": 20_000, "expenses": 100},
            21_000,
            "build-with-cash-discipline",
            id="cash-drop",
        ),
        pytest.param(
            {},
            None,
            "highest-leverage-build",
            id="default",
        ),
    ],
)
def test_each_branch_can_be_selected_in_isolation(
    overrides,
    previous_cash,
    expected_signal,
):
    direction = choose_direction(
        checkin(**overrides),
        PROJECT,
        previous_cash=previous_cash,
    )

    assert direction.signal == expected_signal


def test_urgent_blocker_outranks_low_capacity_and_cash_pressure():
    direction = choose_direction(
        checkin(
            cash=500,
            free_hours=0.25,
            energy=1,
            blocker="Production outage affecting customers",
        ),
        PROJECT,
    )

    assert direction.signal == "stability-first"


def test_low_capacity_deliberately_outranks_cash_pressure():
    direction = choose_direction(
        checkin(cash=500, free_hours=0.33, energy=1),
        PROJECT,
    )

    assert direction.signal == "minimum-viable-progress"


def test_cash_pressure_threshold_boundaries_and_override():
    just_below = choose_direction(checkin(cash=9_999.99), PROJECT)
    at_default_threshold = choose_direction(checkin(cash=10_000), PROJECT)
    zero_balance = choose_direction(checkin(cash=0), PROJECT)
    negative_balance = choose_direction(checkin(cash=-500), PROJECT)
    missing_balance = choose_direction(checkin(cash=None), PROJECT)
    custom_threshold = choose_direction(
        checkin(cash=15_000),
        PROJECT,
        severe_cash_pressure_threshold=20_000,
    )

    assert just_below.signal == "cash-protection"
    assert at_default_threshold.signal == "highest-leverage-build"
    assert zero_balance.signal == "cash-protection"
    assert negative_balance.signal == "cash-protection"
    assert missing_balance.signal == "highest-leverage-build"
    assert custom_threshold.signal == "cash-protection"


@pytest.mark.parametrize(
    "blocker",
    [
        "Went to the bank to deposit a check",
        "I corrected a misleading chart label",
        "Leadership workshop notes need organizing",
        "A cron job needs routine maintenance",
        "Fix client-side rendering",
        "No urgent blocker today",
        "Deadline met; only documentation remains",
        "No clients were affected",
    ],
)
def test_ambiguous_words_do_not_trigger_urgent_or_lead_branches(blocker):
    direction = choose_direction(checkin(blocker=blocker), PROJECT)

    assert direction.signal == "highest-leverage-build"


def test_specific_bank_account_emergency_remains_urgent():
    direction = choose_direction(
        checkin(blocker="My bank account is locked"),
        PROJECT,
    )

    assert direction.signal == "stability-first"


def test_common_production_down_wording_is_urgent():
    direction = choose_direction(
        checkin(blocker="Production is down"),
        PROJECT,
    )

    assert direction.signal == "stability-first"


@pytest.mark.parametrize(
    "blocker",
    [
        "The production incident has been resolved",
        "The production incident, now resolved, needs a postmortem",
    ],
)
def test_resolved_production_incidents_are_not_urgent(blocker):
    direction = choose_direction(checkin(blocker=blocker), PROJECT)

    assert direction.signal == "highest-leverage-build"


@pytest.mark.parametrize(
    "blocker",
    [
        "Finding qualified clients is my blocker",
        "No qualified clients yet",
    ],
)
def test_common_qualified_client_wording_selects_lead_branch(blocker):
    direction = choose_direction(checkin(blocker=blocker), PROJECT)

    assert direction.signal == "revenue-pipeline"


@pytest.mark.parametrize(
    "blocker",
    [
        "Deadline met for project A; production outage affects project B",
        "Production incident resolved, but the site is down again",
        "No urgent blocker yesterday; system down today",
    ],
)
def test_resolved_context_does_not_hide_a_separate_emergency(blocker):
    direction = choose_direction(checkin(blocker=blocker), PROJECT)

    assert direction.signal == "stability-first"


def test_time_and_energy_fit_can_outweigh_an_oversized_quest_priority():
    fitting_quest = {
        "title": "Complete the focused increment",
        "priority": 5,
        "estimated_minutes": 30,
        "energy_required": 2,
    }
    oversized_quest = {
        "title": "Attempt the large migration",
        "priority": 8,
        "estimated_minutes": 120,
        "energy_required": 5,
    }

    selected = _best_fitting_quest(
        [oversized_quest, fitting_quest],
        free_hours=1,
        energy=3,
    )

    assert selected is fitting_quest


def test_low_capacity_branch_only_recommends_a_quest_that_fits():
    fitting_quest = {
        "title": "Send the small status update",
        "priority": 1,
        "estimated_minutes": 15,
        "energy_required": 1,
    }
    oversized_quest = {
        "title": "Complete the three-hour migration",
        "priority": 10,
        "estimated_minutes": 180,
        "energy_required": 5,
    }

    direction = choose_direction(
        checkin(free_hours=0.33, energy=1),
        PROJECT,
        open_quests=[oversized_quest, fitting_quest],
    )

    assert direction.signal == "minimum-viable-progress"
    assert fitting_quest["title"] in direction.main_quest
    assert oversized_quest["title"] not in direction.main_quest


def test_low_capacity_branch_falls_back_when_no_quest_fits():
    oversized_quest = {
        "title": "Complete the three-hour migration",
        "priority": 10,
        "estimated_minutes": 180,
        "energy_required": 5,
    }

    direction = choose_direction(
        checkin(free_hours=0.25, energy=1),
        PROJECT,
        open_quests=[oversized_quest],
    )

    assert direction.signal == "minimum-viable-progress"
    assert "no more than 15 minutes" in direction.main_quest
    assert "do not try to finish the full action" in direction.main_quest
    assert oversized_quest["title"] not in direction.main_quest


def test_income_preference_is_a_bonus_not_naive_keyword_matching():
    regular_quest = {
        "title": "Ship the dashboard",
        "priority": 7,
        "estimated_minutes": 45,
        "energy_required": 3,
    }
    income_quest = {
        "title": "Contact a qualified client",
        "priority": 5,
        "estimated_minutes": 30,
        "energy_required": 2,
    }
    false_positive_quest = {
        "title": "Fix client-side rendering in a cron job",
        "priority": 5,
        "estimated_minutes": 30,
        "energy_required": 2,
    }

    without_income_preference = _best_fitting_quest(
        [regular_quest, income_quest],
        free_hours=1,
        energy=3,
    )
    with_income_preference = _best_fitting_quest(
        [regular_quest, income_quest],
        free_hours=1,
        energy=3,
        prefer_income=True,
    )
    with_ambiguous_words = _best_fitting_quest(
        [regular_quest, false_positive_quest],
        free_hours=1,
        energy=3,
        prefer_income=True,
    )

    assert without_income_preference is regular_quest
    assert with_income_preference is income_quest
    assert with_ambiguous_words is regular_quest


def test_terminal_quests_are_not_recommended():
    completed_quest = {
        "title": "Already completed",
        "status": "completed",
        "priority": 10,
        "estimated_minutes": 10,
        "energy_required": 1,
    }
    open_quest = {
        "title": "Still open",
        "status": "backlog",
        "priority": 1,
        "estimated_minutes": 30,
        "energy_required": 2,
    }

    selected = _best_fitting_quest(
        [completed_quest, open_quest],
        free_hours=1,
        energy=3,
    )

    assert selected is open_quest
