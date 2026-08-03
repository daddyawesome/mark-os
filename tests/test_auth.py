import os
import subprocess
import sys
from pathlib import Path

import pytest

import app.main as main_module
from app.auth import DEFAULT_SESSION_SECRET, validate_session_secret


def test_default_session_secret_is_allowed_for_local_development():
    validate_session_secret(
        is_railway=False,
        session_secret=DEFAULT_SESSION_SECRET,
    )


@pytest.mark.parametrize(
    "session_secret",
    ["", "   ", DEFAULT_SESSION_SECRET],
)
def test_railway_rejects_blank_or_default_session_secret(session_secret):
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        validate_session_secret(
            is_railway=True,
            session_secret=session_secret,
        )


def test_railway_accepts_configured_session_secret():
    validate_session_secret(
        is_railway=True,
        session_secret="a-unique-random-production-session-secret",
    )


def test_startup_validates_auth_before_database_initialization(monkeypatch):
    calls = []

    def reject_configuration():
        calls.append("validate")
        raise RuntimeError("unsafe configuration")

    def initialize_database():
        calls.append("database")

    monkeypatch.setattr(
        main_module,
        "validate_auth_configuration",
        reject_configuration,
    )
    monkeypatch.setattr(main_module, "init_db", initialize_database)

    with pytest.raises(RuntimeError, match="unsafe configuration"):
        main_module.startup()

    assert calls == ["validate"]


def test_env_example_documents_required_auth_settings():
    env_example = Path(__file__).resolve().parent.parent / ".env.example"
    contents = env_example.read_text()

    assert "MARK_OS_USERNAME=" in contents
    assert "MARK_OS_PASSWORD=" in contents
    assert "SESSION_SECRET=" in contents
    assert "MARK_OS_DB_PATH=" in contents


def test_railway_default_secret_stops_before_database_creation(tmp_path):
    database_path = tmp_path / "must-not-be-created.db"
    environment = os.environ.copy()
    environment.pop("SESSION_SECRET", None)
    environment["RAILWAY_ENVIRONMENT"] = "test"
    environment["MARK_OS_DB_PATH"] = str(database_path)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.main import startup; startup()",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "SESSION_SECRET" in result.stderr
    assert not database_path.exists()
