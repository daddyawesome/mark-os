from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


APPLICATION_LOGGER = "mark_os.application"
_ERROR_LEVELS = frozenset({"ERROR", "CRITICAL"})
_MAX_HOURS = 24 * 31
_MAX_SAMPLES = 100


@dataclass(frozen=True)
class ErrorSample:
    timestamp: str
    event: str
    correlation_id: str | None
    path: str | None
    status_code: int | None
    exception_type: str | None


@dataclass(frozen=True)
class ErrorSummary:
    window_start_utc: str
    window_end_utc: str
    hours: int
    error_count: int
    unique_correlation_ids: int
    by_event: dict[str, int]
    samples: list[ErrorSample]
    source_lines: int
    malformed_lines: int
    ignored_lines: int
    out_of_window_lines: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def parse_utc_timestamp(
    value: Any,
) -> datetime | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    if not clean:
        return None
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _mapping_from_message(
    value: Any,
) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return None
    clean = value.strip()
    if not clean.startswith("{"):
        return None
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _application_event(
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    direct = dict(payload)
    if direct.get("logger") == APPLICATION_LOGGER:
        return direct

    for key in ("message", "msg"):
        nested = _mapping_from_message(
            direct.get(key)
        )
        if (
            nested is not None
            and nested.get("logger") == APPLICATION_LOGGER
        ):
            if "timestamp" not in nested:
                nested["timestamp"] = direct.get("timestamp")
            if "level" not in nested:
                nested["level"] = (
                    direct.get("level")
                    or direct.get("severity")
                )
            return nested
    return None


def _safe_text(
    value: Any,
    *,
    maximum: int = 160,
) -> str | None:
    if not isinstance(value, str):
        return None
    clean = " ".join(
        value.replace("\r", " ")
        .replace("\n", " ")
        .split()
    )
    if not clean:
        return None
    return clean[:maximum]


def _safe_status_code(
    value: Any,
) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if 100 <= parsed <= 599:
        return parsed
    return None


def _sample_from_event(
    event: Mapping[str, Any],
    timestamp: datetime,
) -> ErrorSample:
    return ErrorSample(
        timestamp=_iso_utc(timestamp),
        event=(
            _safe_text(
                event.get("event")
                or event.get("message"),
                maximum=120,
            )
            or "unknown_error"
        ),
        correlation_id=_safe_text(
            event.get("correlation_id"),
            maximum=64,
        ),
        path=_safe_text(
            event.get("path"),
            maximum=200,
        ),
        status_code=_safe_status_code(
            event.get("status_code")
        ),
        exception_type=_safe_text(
            event.get("exception_type"),
            maximum=120,
        ),
    )


def summarize_error_lines(
    lines: Iterable[str | bytes],
    *,
    now_utc: datetime | None = None,
    hours: int = 24,
    max_samples: int = 20,
) -> ErrorSummary:
    """Summarize bounded MARK-OS JSON application errors without raw payloads."""
    if not 1 <= hours <= _MAX_HOURS:
        raise ValueError(
            f"hours must be between 1 and {_MAX_HOURS}."
        )
    if not 0 <= max_samples <= _MAX_SAMPLES:
        raise ValueError(
            f"max_samples must be between 0 and {_MAX_SAMPLES}."
        )

    resolved_now = now_utc or datetime.now(timezone.utc)
    if resolved_now.tzinfo is None:
        raise ValueError(
            "now_utc must be timezone-aware."
        )
    resolved_now = resolved_now.astimezone(
        timezone.utc
    )
    window_start = resolved_now - timedelta(
        hours=hours
    )

    source_lines = 0
    malformed_lines = 0
    ignored_lines = 0
    out_of_window_lines = 0
    event_counts: Counter[str] = Counter()
    correlations: set[str] = set()
    accepted: list[tuple[datetime, ErrorSample]] = []

    for raw_line in lines:
        source_lines += 1
        if isinstance(raw_line, bytes):
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                malformed_lines += 1
                continue
        else:
            line = raw_line

        clean = line.strip()
        if not clean:
            ignored_lines += 1
            continue
        try:
            payload = json.loads(clean)
        except json.JSONDecodeError:
            malformed_lines += 1
            continue
        if not isinstance(payload, dict):
            malformed_lines += 1
            continue

        event = _application_event(payload)
        if event is None:
            ignored_lines += 1
            continue

        timestamp = parse_utc_timestamp(
            event.get("timestamp")
        )
        if timestamp is None:
            malformed_lines += 1
            continue
        if not (
            window_start
            <= timestamp
            <= resolved_now
        ):
            out_of_window_lines += 1
            continue

        level = str(
            event.get("level")
            or event.get("severity")
            or ""
        ).strip().upper()
        if level not in _ERROR_LEVELS:
            ignored_lines += 1
            continue

        sample = _sample_from_event(
            event,
            timestamp,
        )
        event_counts[sample.event] += 1
        if sample.correlation_id:
            correlations.add(
                sample.correlation_id
            )
        accepted.append(
            (timestamp, sample)
        )

    accepted.sort(
        key=lambda item: (
            item[0],
            item[1].event,
            item[1].correlation_id or "",
        ),
        reverse=True,
    )
    samples = [
        item[1]
        for item in accepted[:max_samples]
    ]

    return ErrorSummary(
        window_start_utc=_iso_utc(window_start),
        window_end_utc=_iso_utc(resolved_now),
        hours=hours,
        error_count=sum(event_counts.values()),
        unique_correlation_ids=len(correlations),
        by_event=dict(
            sorted(
                event_counts.items(),
                key=lambda item: (
                    -item[1],
                    item[0],
                ),
            )
        ),
        samples=samples,
        source_lines=source_lines,
        malformed_lines=malformed_lines,
        ignored_lines=ignored_lines,
        out_of_window_lines=out_of_window_lines,
    )
