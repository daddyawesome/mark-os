from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pytest

from app.services.error_summary import (
    summarize_error_lines,
)
from app.services.observability import (
    LOGGER_NAME,
    JsonEventFormatter,
)


NOW = datetime(
    2026,
    8,
    6,
    14,
    0,
    0,
    tzinfo=timezone.utc,
)


def _line(
    *,
    timestamp: str,
    event: str,
    level: str = "ERROR",
    **fields,
) -> str:
    payload = {
        "timestamp": timestamp,
        "level": level,
        "logger": LOGGER_NAME,
        "message": event,
        "event": event,
        **fields,
    }
    return json.dumps(payload)


def test_json_formatter_includes_railway_message_and_event():
    record = logging.LogRecord(
        LOGGER_NAME,
        logging.ERROR,
        __file__,
        1,
        "fallback-message",
        (),
        None,
    )
    record.event_name = "application_error"
    record.event_fields = {
        "correlation_id": "request-123",
    }

    payload = json.loads(
        JsonEventFormatter().format(record)
    )
    assert payload["message"] == "application_error"
    assert payload["event"] == "application_error"
    assert payload["level"] == "ERROR"
    assert payload["correlation_id"] == "request-123"


def test_previous_24_hour_count_is_inclusive_at_both_boundaries():
    lines = [
        _line(
            timestamp="2026-08-05T14:00:00Z",
            event="application_error",
            correlation_id="oldest",
        ),
        _line(
            timestamp="2026-08-06T14:00:00Z",
            event="server_error_response",
            correlation_id="newest",
        ),
        _line(
            timestamp="2026-08-05T13:59:59Z",
            event="outside",
        ),
        _line(
            timestamp="2026-08-06T14:00:01Z",
            event="future",
        ),
    ]

    summary = summarize_error_lines(
        lines,
        now_utc=NOW,
    )

    assert summary.error_count == 2
    assert summary.out_of_window_lines == 2
    assert summary.by_event == {
        "application_error": 1,
        "server_error_response": 1,
    }
    assert [
        sample.correlation_id
        for sample in summary.samples
    ] == [
        "newest",
        "oldest",
    ]


def test_railway_wrapper_message_is_parsed_without_exposing_wrapper_data():
    inner = _line(
        timestamp="2026-08-06T13:00:00Z",
        event="startup_failure",
        correlation_id="startup",
        exception_type="RuntimeError",
    )
    wrapper = json.dumps(
        {
            "timestamp": "2026-08-06T13:00:00Z",
            "severity": "error",
            "message": inner,
            "deploymentId": "private-deployment-id",
        }
    )

    summary = summarize_error_lines(
        [wrapper],
        now_utc=NOW,
    )

    assert summary.error_count == 1
    assert summary.samples[0].event == "startup_failure"
    assert summary.samples[0].exception_type == "RuntimeError"
    result = json.dumps(
        summary.as_dict()
    )
    assert "private-deployment-id" not in result


def test_non_application_non_error_and_malformed_lines_are_classified():
    lines = [
        "",
        "not-json",
        json.dumps(["not", "an", "object"]),
        json.dumps(
            {
                "timestamp": "2026-08-06T13:00:00Z",
                "level": "ERROR",
                "logger": "uvicorn.error",
                "event": "server_error",
            }
        ),
        _line(
            timestamp="2026-08-06T13:00:00Z",
            event="authentication_succeeded",
            level="INFO",
        ),
        _line(
            timestamp="not-a-time",
            event="application_error",
        ),
    ]

    summary = summarize_error_lines(
        lines,
        now_utc=NOW,
    )

    assert summary.error_count == 0
    assert summary.malformed_lines == 3
    assert summary.ignored_lines == 3


def test_samples_use_allowlisted_fields_and_drop_secret_payloads():
    line = _line(
        timestamp="2026-08-06T13:30:00Z",
        event="application_error",
        correlation_id="safe-request",
        path="/crm/leads/1",
        status_code=500,
        exception_type="RuntimeError",
        password="never-show",
        authorization="Bearer never-show",
        traceback_frames=[
            {
                "file": "private.py",
                "line": 10,
            }
        ],
    )

    summary = summarize_error_lines(
        [line],
        now_utc=NOW,
    )
    payload = json.dumps(
        summary.as_dict()
    )

    assert summary.error_count == 1
    assert summary.samples[0].path == "/crm/leads/1"
    assert summary.samples[0].status_code == 500
    assert "never-show" not in payload
    assert "authorization" not in payload
    assert "traceback_frames" not in payload
    assert "private.py" not in payload


def test_counts_are_sorted_and_samples_are_bounded():
    lines = [
        _line(
            timestamp=f"2026-08-06T13:{minute:02d}:00Z",
            event=event,
            correlation_id=f"request-{minute}",
        )
        for minute, event in (
            (1, "zeta_error"),
            (2, "alpha_error"),
            (3, "alpha_error"),
            (4, "beta_error"),
            (5, "beta_error"),
        )
    ]

    summary = summarize_error_lines(
        lines,
        now_utc=NOW,
        max_samples=2,
    )

    assert list(summary.by_event.items()) == [
        ("alpha_error", 2),
        ("beta_error", 2),
        ("zeta_error", 1),
    ]
    assert len(summary.samples) == 2
    assert [
        sample.correlation_id
        for sample in summary.samples
    ] == [
        "request-5",
        "request-4",
    ]


def test_empty_input_produces_zero_safe_summary():
    summary = summarize_error_lines(
        [],
        now_utc=NOW,
    )

    assert summary.error_count == 0
    assert summary.unique_correlation_ids == 0
    assert summary.by_event == {}
    assert summary.samples == []
    assert summary.source_lines == 0


@pytest.mark.parametrize(
    ("hours", "max_samples"),
    [
        (0, 10),
        (24 * 31 + 1, 10),
        (24, -1),
        (24, 101),
    ],
)
def test_summary_bounds_fail_closed(
    hours,
    max_samples,
):
    with pytest.raises(ValueError):
        summarize_error_lines(
            [],
            now_utc=NOW,
            hours=hours,
            max_samples=max_samples,
        )


def test_naive_now_is_rejected():
    with pytest.raises(ValueError):
        summarize_error_lines(
            [],
            now_utc=datetime(
                2026,
                8,
                6,
                14,
                0,
                0,
            ),
        )
