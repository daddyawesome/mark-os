from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest
from fastapi import Request
from fastapi.responses import PlainTextResponse

from app import database, main
from app.routes import auth as auth_routes
from app.services.observability import (
    LOGGER_NAME,
    ObservabilityMiddleware,
    configure_observability,
    log_event,
    normalize_request_id,
)


def _request(
    *,
    path: str = "/test",
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "headers": headers or [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


@pytest.fixture
def captured_events():
    logger = logging.getLogger(LOGGER_NAME)
    old_handlers = list(logger.handlers)
    old_level = logger.level
    old_propagate = logger.propagate
    buffer = io.StringIO()

    configure_observability(
        stream=buffer,
        force=True,
    )
    try:
        yield buffer
    finally:
        logger.handlers.clear()
        for handler in old_handlers:
            logger.addHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate


def _events(buffer: io.StringIO) -> list[dict]:
    return [
        json.loads(line)
        for line in buffer.getvalue().splitlines()
        if line.strip()
    ]


def test_structured_event_is_json_and_redacts_sensitive_fields(
    captured_events,
):
    log_event(
        "authentication_failed",
        level=logging.WARNING,
        correlation_id="request-123",
        username_present=True,
        password="do-not-log",
        authorization="Bearer do-not-log",
        nested={
            "session_token": "do-not-log",
            "safe": "visible",
        },
    )

    event = _events(captured_events)[0]
    assert event["event"] == "authentication_failed"
    assert event["level"] == "WARNING"
    assert event["logger"] == LOGGER_NAME
    assert event["correlation_id"] == "request-123"
    assert event["username_present"] is True
    assert event["password"] == "[REDACTED]"
    assert event["authorization"] == "[REDACTED]"
    assert event["nested"]["session_token"] == "[REDACTED]"
    assert event["nested"]["safe"] == "visible"
    assert "do-not-log" not in captured_events.getvalue()


def test_request_id_accepts_only_short_safe_values():
    assert normalize_request_id("client-request_123") == (
        "client-request_123"
    )

    generated = normalize_request_id(
        "<script>unsafe</script>"
    )
    assert len(generated) == 32
    assert generated.isalnum()

    generated_long = normalize_request_id(
        "x" * 65
    )
    assert len(generated_long) == 32


def test_middleware_returns_request_id_on_success(
    captured_events,
):
    middleware = ObservabilityMiddleware(
        lambda scope, receive, send: None,
        secure_transport=False,
    )
    request = _request(
        headers=[
            (
                b"x-request-id",
                b"client-request-456",
            )
        ],
    )

    async def call_next(received_request):
        assert (
            received_request.state.correlation_id
            == "client-request-456"
        )
        return PlainTextResponse("ok")

    response = asyncio.run(
        middleware.dispatch(
            request,
            call_next,
        )
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == (
        "client-request-456"
    )
    assert _events(captured_events) == []


def test_middleware_logs_exception_without_message_and_returns_safe_500(
    captured_events,
):
    middleware = ObservabilityMiddleware(
        lambda scope, receive, send: None,
        secure_transport=False,
    )
    request = _request(
        path="/failing-route",
        headers=[
            (b"x-request-id", b"failure-789")
        ],
    )

    async def call_next(_):
        raise RuntimeError(
            "password=should-never-appear"
        )

    response = asyncio.run(
        middleware.dispatch(
            request,
            call_next,
        )
    )

    assert response.status_code == 500
    assert response.body == b"Internal Server Error"
    assert response.headers["X-Request-ID"] == "failure-789"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store, max-age=0"

    event = _events(captured_events)[0]
    assert event["event"] == "application_error"
    assert event["exception_type"] == "RuntimeError"
    assert event["path"] == "/failing-route"
    assert event["correlation_id"] == "failure-789"
    assert event["traceback_frames"]
    assert (
        "password=should-never-appear"
        not in captured_events.getvalue()
    )


def test_startup_logs_auth_configuration_failure_before_database_access(
    monkeypatch,
    captured_events,
):
    database_called = False

    def fail_configuration():
        raise RuntimeError(
            "SESSION_SECRET=should-never-appear"
        )

    def unexpected_database_call():
        nonlocal database_called
        database_called = True

    monkeypatch.setattr(
        main,
        "validate_auth_configuration",
        fail_configuration,
    )
    monkeypatch.setattr(
        main,
        "init_db",
        unexpected_database_call,
    )

    with pytest.raises(RuntimeError):
        main.startup()

    assert database_called is False
    event = _events(captured_events)[0]
    assert event["event"] == "startup_failure"
    assert event["stage"] == "auth_configuration"
    assert event["exception_type"] == "RuntimeError"
    assert (
        "SESSION_SECRET=should-never-appear"
        not in captured_events.getvalue()
    )


def test_startup_logs_database_initialization_failure(
    monkeypatch,
    captured_events,
):
    monkeypatch.setattr(
        main,
        "validate_auth_configuration",
        lambda: None,
    )

    def fail_database():
        raise OSError(
            "database password should never appear"
        )

    monkeypatch.setattr(
        main,
        "init_db",
        fail_database,
    )

    with pytest.raises(OSError):
        main.startup()

    event = _events(captured_events)[0]
    assert event["event"] == "startup_failure"
    assert event["stage"] == "database_initialization"
    assert event["exception_type"] == "OSError"
    assert (
        "database password should never appear"
        not in captured_events.getvalue()
    )


def test_failed_login_logs_summary_without_username_or_password(
    tmp_path,
    monkeypatch,
    captured_events,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "login-observability.db")
    database.init_db()
    request = _request(
        path="/login",
        method="POST",
    )
    request.state.correlation_id = "login-failure-1"

    monkeypatch.setattr(
        auth_routes,
        "authenticate_credentials",
        lambda username, password: None,
    )
    monkeypatch.setattr(
        auth_routes,
        "credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        auth_routes.templates,
        "TemplateResponse",
        lambda **kwargs: kwargs,
    )

    response = auth_routes.login_submit(
        request,
        username="private-user@example.com",
        password="private-password",
        next="/",
    )

    assert response["status_code"] == 401
    event = _events(captured_events)[0]
    assert event["event"] == "authentication_failed"
    assert event["status_code"] == 401
    assert event["username_present"] is True
    assert event["configured"] is True
    assert "private-user@example.com" not in captured_events.getvalue()
    assert "private-password" not in captured_events.getvalue()


def test_authorization_denial_logs_only_actor_id_role_method_and_path(
    monkeypatch,
    captured_events,
):
    user = {
        "id": 7,
        "username": "do-not-log-this",
        "display_name": "Do Not Log",
        "role": "lead_sourcer",
    }
    request = _request(
        path="/settings/users",
        method="GET",
    )
    request.state.correlation_id = "denied-request-1"

    monkeypatch.setattr(
        main,
        "current_user",
        lambda request: user,
    )
    monkeypatch.setattr(
        main,
        "can_access_request",
        lambda user, method, path: False,
    )

    async def call_next(_):
        raise AssertionError(
            "Denied request must not reach the route."
        )

    response = asyncio.run(
        main.login_and_permission_guard(
            request,
            call_next,
        )
    )

    assert response.status_code == 303
    event = _events(captured_events)[0]
    assert event["event"] == "authorization_denied"
    assert event["user_id"] == 7
    assert event["user_role"] == "lead_sourcer"
    assert event["method"] == "GET"
    assert event["path"] == "/settings/users"
    assert event["status_code"] == 303
    assert "do-not-log-this" not in captured_events.getvalue()
    assert "Do Not Log" not in captured_events.getvalue()
