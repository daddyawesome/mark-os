from __future__ import annotations

import json
import urllib.error

import pytest

from app import database
from app.services import provider_gateway
from app.services.agent_audit import create_agent_run, list_agent_steps
from app.services.chat import create_chat_session, save_chat_message
from app.services.context_builder import build_context
from app.services.personal_scope import user_scope
from app.services.team_users import create_member


REQUIRED_ENV = {
    "OPENAI_API_KEY": "sk-test-key",
    "OPENAI_MODEL": "gpt-test-model",
    "OPENAI_INPUT_PRICE_MICROUSD_PER_1K": "100",
    "OPENAI_OUTPUT_PRICE_MICROUSD_PER_1K": "200",
    "MARK_OS_AI_MONTHLY_BUDGET_MICROUSD": "3500000",
}


def _set_required_env(monkeypatch, overrides: dict | None = None) -> None:
    values = dict(REQUIRED_ENV)
    values.update(overrides or {})
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def gateway_database(tmp_path, monkeypatch):
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "phase-8-4.db")
    database.init_db()
    with database.get_db() as db:
        owner_id = int(
            db.execute("SELECT id FROM users WHERE role = 'owner'").fetchone()[0]
        )
    return owner_id


def _create_run(db, *, owner_id, message="Any notes on my week?"):
    session = create_chat_session(db, user_id=owner_id)
    user_message = save_chat_message(
        db,
        session_id=session["id"],
        role="user",
        content=message,
        user_id=owner_id,
    )
    packet = build_context(db, new_message=message, user_id=owner_id)
    with user_scope(owner_id):
        run_result = create_agent_run(
            db,
            session_id=session["id"],
            user_message_id=user_message.message["id"],
            intent="general_chat",
            loop_selected="routine_chat",
        )
    return run_result.run, packet


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_load_provider_config_fails_closed_when_env_is_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert provider_gateway.load_provider_config() is None


def test_load_provider_config_fails_closed_on_invalid_price(monkeypatch):
    _set_required_env(monkeypatch, {"OPENAI_INPUT_PRICE_MICROUSD_PER_1K": "not-a-number"})
    assert provider_gateway.load_provider_config() is None


def test_load_provider_config_applies_defaults_and_clamps(monkeypatch):
    _set_required_env(
        monkeypatch,
        {
            "OPENAI_MAX_OUTPUT_TOKENS": "999999",
            "MARK_OS_AI_DAILY_REQUEST_CAP": "0",
        },
    )
    config = provider_gateway.load_provider_config()

    assert config is not None
    assert config.max_output_tokens == provider_gateway.MAX_OUTPUT_TOKENS_CEILING
    assert config.daily_request_cap == 1
    assert config.daily_budget_microusd == max(1, config.monthly_budget_microusd // 30)
    assert config.base_url == provider_gateway.DEFAULT_BASE_URL


def test_disabled_when_unconfigured_records_skipped_step(gateway_database, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with database.get_db() as db:
        run, packet = _create_run(db, owner_id=gateway_database)
        result = provider_gateway.request_ai_completion(db, run_id=run["id"], context_packet=packet)

        assert result.allowed is False
        assert result.reason == "ai_not_configured"
        assert result.content is None

        steps = list_agent_steps(db, run["id"])
        assert len(steps) == 1
        assert steps[0]["status"] == "skipped"
        assert steps[0]["provider"] == "disabled"


def test_successful_call_records_completed_step_with_real_usage(gateway_database, monkeypatch):
    _set_required_env(monkeypatch)

    def fake_urlopen(request, timeout=None):
        return _FakeResponse(
            {
                "choices": [{"message": {"content": "Focus on the highest-leverage task."}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 40},
            }
        )

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", fake_urlopen)

    with database.get_db() as db:
        run, packet = _create_run(db, owner_id=gateway_database)
        result = provider_gateway.request_ai_completion(db, run_id=run["id"], context_packet=packet)

        assert result.allowed is True
        assert result.content == "Focus on the highest-leverage task."
        assert result.provider == "openai"

        steps = list_agent_steps(db, run["id"])
        assert len(steps) == 1
        assert steps[0]["status"] == "completed"
        assert steps[0]["input_tokens"] == 120
        assert steps[0]["output_tokens"] == 40
        expected_cost = (120 * 100 + 999) // 1000 + (40 * 200 + 999) // 1000
        assert steps[0]["estimated_cost_microusd"] == expected_cost


def test_provider_failure_records_failed_step_and_returns_no_content(gateway_database, monkeypatch):
    _set_required_env(monkeypatch)

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", fake_urlopen)

    with database.get_db() as db:
        run, packet = _create_run(db, owner_id=gateway_database)
        result = provider_gateway.request_ai_completion(db, run_id=run["id"], context_packet=packet)

        assert result.allowed is True
        assert result.reason == "provider_call_failed"
        assert result.content is None

        steps = list_agent_steps(db, run["id"])
        assert len(steps) == 1
        assert steps[0]["status"] == "failed"
        assert steps[0]["input_tokens"] == 0
        assert steps[0]["estimated_cost_microusd"] == 0
        assert steps[0]["error_message"]


def test_budget_exhausted_skips_the_call_without_hitting_network(gateway_database, monkeypatch):
    _set_required_env(monkeypatch, {"MARK_OS_AI_MONTHLY_BUDGET_MICROUSD": "1"})

    def fail_if_called(request, timeout=None):
        raise AssertionError("Provider must not be called when the budget is exhausted")

    monkeypatch.setattr(provider_gateway.urllib.request, "urlopen", fail_if_called)

    with database.get_db() as db:
        run, packet = _create_run(db, owner_id=gateway_database)
        result = provider_gateway.request_ai_completion(db, run_id=run["id"], context_packet=packet)

        assert result.allowed is False
        assert result.reason in {
            "single_request_exceeds_daily_budget",
            "daily_budget_exhausted",
            "monthly_budget_exhausted",
        }
        assert result.content is None

        steps = list_agent_steps(db, run["id"])
        assert len(steps) == 1
        assert steps[0]["status"] == "skipped"


def test_daily_request_cap_blocks_further_calls(gateway_database, monkeypatch):
    _set_required_env(monkeypatch, {"MARK_OS_AI_DAILY_REQUEST_CAP": "1"})
    config = provider_gateway.load_provider_config()

    with database.get_db() as db:
        first_run, first_packet = _create_run(db, owner_id=gateway_database, message="First question")
        db.execute(
            """
            INSERT INTO agent_steps (
                user_id, run_id, step_number, step_type, name, status,
                provider, model, input_tokens, output_tokens,
                estimated_cost_microusd, started_at, completed_at
            )
            VALUES (?, ?, 1, 'ai_call', 'routine_chat', 'completed',
                    'openai', ?, 10, 10, 5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (gateway_database, first_run["id"], config.model),
        )

        second_run, second_packet = _create_run(db, owner_id=gateway_database, message="Second question")
        decision = provider_gateway.check_budget(
            db, config, input_tokens=second_packet.estimated_tokens
        )

    assert decision.allowed is False
    assert decision.reason == "daily_request_cap_reached"


def test_budget_spend_is_global_not_per_user(gateway_database, monkeypatch):
    _set_required_env(
        monkeypatch,
        {
            "MARK_OS_AI_MONTHLY_BUDGET_MICROUSD": "1000",
            "MARK_OS_AI_DAILY_BUDGET_MICROUSD": "1000",
        },
    )
    config = provider_gateway.load_provider_config()
    # Fix the day/month windows so a same-month, earlier-day spend counts
    # toward the monthly total without also tripping the daily checks.
    monkeypatch.setattr(provider_gateway, "_month_start", lambda: "2020-01-01 00:00:00")
    monkeypatch.setattr(provider_gateway, "_day_start", lambda: "2020-01-15 00:00:00")

    with database.get_db() as db:
        member = create_member(
            db,
            username="member",
            display_name="Member",
            password="member-password-123",
            password_confirmation="member-password-123",
        )
        member_id = int(member["id"])

        # Spend recorded entirely under a different user's own run, earlier
        # this month but before today's window.
        member_run, _member_packet = _create_run(
            db, owner_id=member_id, message="Member question"
        )
        db.execute(
            """
            INSERT INTO agent_steps (
                user_id, run_id, step_number, step_type, name, status,
                provider, model, input_tokens, output_tokens,
                estimated_cost_microusd, started_at, completed_at, created_at
            )
            VALUES (?, ?, 1, 'ai_call', 'routine_chat', 'completed',
                    'openai', ?, 10, 10, 900,
                    '2020-01-05 00:00:00', '2020-01-05 00:00:00', '2020-01-05 00:00:00')
            """,
            (member_id, member_run["id"], config.model),
        )

        owner_run, owner_packet = _create_run(db, owner_id=gateway_database)
        decision = provider_gateway.check_budget(
            db, config, input_tokens=owner_packet.estimated_tokens
        )

    assert decision.allowed is False
    assert decision.reason == "monthly_budget_exhausted"
