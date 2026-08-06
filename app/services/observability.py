from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import traceback
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, TextIO

from fastapi import Request
from fastapi.responses import PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.services.security import apply_security_headers


LOGGER_NAME = "mark_os.application"
REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "cookie",
    "authorization",
    "session",
    "api_key",
    "apikey",
    "client_secret",
)
_MAX_TEXT_LENGTH = 500
_correlation_id: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar(
        "mark_os_correlation_id",
        default=None,
    )
)


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().casefold()
    return any(
        fragment in normalized
        for fragment in _SENSITIVE_KEY_FRAGMENTS
    )


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        clean = value.replace("\r", " ").replace("\n", " ")
        if len(clean) > _MAX_TEXT_LENGTH:
            return clean[:_MAX_TEXT_LENGTH] + "…"
        return clean

    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if _is_sensitive_key(str(key))
                else _safe_value(item)
            )
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _safe_value(item)
            for item in value
        ]

    return _safe_value(str(value))


def sanitize_fields(
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Redact sensitive keys and normalize values for JSON logging."""
    return {
        str(key): (
            "[REDACTED]"
            if _is_sensitive_key(str(key))
            else _safe_value(value)
        )
        for key, value in fields.items()
    }


def normalize_request_id(
    value: str | None,
) -> str:
    """Accept only a short safe request ID; otherwise generate one."""
    clean = (value or "").strip()
    if _REQUEST_ID_PATTERN.fullmatch(clean):
        return clean
    return uuid.uuid4().hex


def current_correlation_id() -> str | None:
    return _correlation_id.get()


def _bind_correlation_id(
    correlation_id: str,
) -> contextvars.Token[str | None]:
    return _correlation_id.set(correlation_id)


def _reset_correlation_id(
    token: contextvars.Token[str | None],
) -> None:
    _correlation_id.reset(token)


def _actor_fields(
    user: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if user is None:
        return {}

    actor: dict[str, Any] = {}
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        user_id = 0
    if user_id > 0:
        actor["user_id"] = user_id

    try:
        role = str(user["role"] or "").strip().casefold()
    except (KeyError, TypeError):
        role = ""
    if role:
        actor["user_role"] = role

    return actor


def request_event_fields(
    request: Request,
    *,
    user: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deliberately narrow, non-sensitive request summary."""
    state_user = getattr(
        request.state,
        "current_user",
        None,
    )
    correlation_id = (
        getattr(
            request.state,
            "correlation_id",
            None,
        )
        or current_correlation_id()
    )
    fields: dict[str, Any] = {
        "method": request.method.upper(),
        "path": request.url.path,
    }
    if correlation_id:
        fields["correlation_id"] = correlation_id
    fields.update(
        _actor_fields(
            user
            if user is not None
            else state_user
        )
    )
    return fields


def _traceback_frames(
    exc: BaseException,
) -> list[dict[str, Any]]:
    frames = traceback.extract_tb(exc.__traceback__)
    return [
        {
            "file": frame.filename.rsplit("/", 1)[-1],
            "line": frame.lineno,
            "function": frame.name,
        }
        for frame in frames[-12:]
    ]


class JsonEventFormatter(logging.Formatter):
    """Serialize application events without using the access-log format."""

    def format(self, record: logging.LogRecord) -> str:
        event_fields = getattr(
            record,
            "event_fields",
            {},
        )
        event_name = getattr(
            record,
            "event_name",
            record.getMessage(),
        )
        payload: dict[str, Any] = {
            "timestamp": _utc_timestamp(),
            "level": record.levelname,
            "logger": record.name,
            "message": event_name,
            "event": event_name,
        }
        payload.update(
            sanitize_fields(event_fields)
        )
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def configure_observability(
    *,
    stream: TextIO | None = None,
    force: bool = False,
) -> logging.Logger:
    """Configure one JSON application logger, separate from Uvicorn access logs."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if force:
        logger.handlers.clear()

    if not logger.handlers:
        handler = logging.StreamHandler(
            stream or sys.stdout
        )
        handler.setFormatter(
            JsonEventFormatter()
        )
        handler._mark_os_observability = True  # type: ignore[attr-defined]
        logger.addHandler(handler)

    return logger


def log_event(
    event_name: str,
    *,
    level: int = logging.INFO,
    request: Request | None = None,
    user: Mapping[str, Any] | None = None,
    correlation_id: str | None = None,
    **fields: Any,
) -> None:
    logger = configure_observability()
    event_fields: dict[str, Any] = {}

    if request is not None:
        event_fields.update(
            request_event_fields(
                request,
                user=user,
            )
        )
    elif user is not None:
        event_fields.update(
            _actor_fields(user)
        )

    resolved_correlation_id = (
        correlation_id
        or event_fields.get("correlation_id")
        or current_correlation_id()
    )
    if resolved_correlation_id:
        event_fields["correlation_id"] = (
            resolved_correlation_id
        )

    event_fields.update(fields)
    logger.log(
        level,
        event_name,
        extra={
            "event_name": event_name,
            "event_fields": event_fields,
        },
    )


def log_exception(
    event_name: str,
    exc: BaseException,
    *,
    request: Request | None = None,
    correlation_id: str | None = None,
    **fields: Any,
) -> None:
    """Log exception type and frame locations, never the exception message."""
    log_event(
        event_name,
        level=logging.ERROR,
        request=request,
        correlation_id=correlation_id,
        exception_type=type(exc).__name__,
        traceback_frames=_traceback_frames(exc),
        **fields,
    )


def log_security_event(
    event_name: str,
    request: Request,
    *,
    user: Mapping[str, Any] | None = None,
    status_code: int,
    **fields: Any,
) -> None:
    log_event(
        event_name,
        level=logging.WARNING,
        request=request,
        user=user,
        status_code=status_code,
        **fields,
    )


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach request IDs and convert unhandled failures to safe responses."""

    def __init__(
        self,
        app,
        *,
        secure_transport: bool,
    ) -> None:
        super().__init__(app)
        self.secure_transport = secure_transport

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        correlation_id = normalize_request_id(
            request.headers.get(REQUEST_ID_HEADER)
        )
        request.state.correlation_id = correlation_id
        token = _bind_correlation_id(
            correlation_id
        )
        started = time.monotonic()

        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                duration_ms = round(
                    (time.monotonic() - started) * 1000,
                    2,
                )
                log_exception(
                    "application_error",
                    exc,
                    request=request,
                    duration_ms=duration_ms,
                )
                response = PlainTextResponse(
                    "Internal Server Error",
                    status_code=500,
                )
                response = apply_security_headers(
                    response,
                    secure_transport=self.secure_transport,
                    cache_private_content=(
                        request.url.path.startswith(
                            "/static/"
                        )
                    ),
                )
            else:
                if response.status_code >= 500:
                    log_event(
                        "server_error_response",
                        level=logging.ERROR,
                        request=request,
                        status_code=response.status_code,
                        duration_ms=round(
                            (
                                time.monotonic()
                                - started
                            )
                            * 1000,
                            2,
                        ),
                    )

            response.headers[
                REQUEST_ID_HEADER
            ] = correlation_id
            return response
        finally:
            _reset_correlation_id(token)
