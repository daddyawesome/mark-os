from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi.responses import JSONResponse

from app.services.database_backup import (
    DEFAULT_MAX_AGE_HOURS,
    BackupStatus,
    check_backup_status,
)
from app.services.observability import log_event, log_exception


HEALTH_VERSION = "0.5.0-observability"
DEFAULT_HEALTH_TIMEOUT_SECONDS = 10
_MAX_HEALTH_BODY_BYTES = 64 * 1024
_MAX_ALERT_CHARACTERS = 1800


@dataclass(frozen=True)
class DatabaseReadiness:
    healthy: bool
    status: str


@dataclass(frozen=True)
class UptimeCheck:
    healthy: bool
    status: str
    status_code: int | None


@dataclass(frozen=True)
class BackupCheck:
    healthy: bool
    status: str
    age_hours: float | None
    max_age_hours: int


@dataclass(frozen=True)
class OwnerAlertDelivery:
    configured: bool
    delivered: bool
    status: str


@dataclass(frozen=True)
class OperationsCheck:
    healthy: bool
    checked_at_utc: str
    uptime: UptimeCheck
    backup: BackupCheck
    alert: OwnerAlertDelivery


UrlOpener = Callable[..., Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_public_url(value: str) -> str:
    clean = value.strip()
    parsed = urlsplit(clean)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "URL must be HTTP or HTTPS without embedded credentials."
        )
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            "",
            "",
        )
    )


def check_database_readiness(
    database_path: str | Path,
) -> DatabaseReadiness:
    """Check the configured SQLite file without creating or changing it."""
    path = Path(database_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        return DatabaseReadiness(
            healthy=False,
            status="unavailable",
        )

    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro",
            uri=True,
            timeout=3,
        )
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("SELECT 1").fetchone()
            users_table = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'users'
                LIMIT 1
                """
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return DatabaseReadiness(
            healthy=False,
            status="unavailable",
        )

    if users_table is None:
        return DatabaseReadiness(
            healthy=False,
            status="not_initialized",
        )
    return DatabaseReadiness(
        healthy=True,
        status="ok",
    )


def build_health_response(
    database_path: str | Path,
) -> JSONResponse:
    readiness = check_database_readiness(database_path)
    payload = {
        "status": "ok" if readiness.healthy else "unavailable",
        "version": HEALTH_VERSION,
        "checks": {
            "database": {
                "status": readiness.status,
            }
        },
    }
    status_code = 200 if readiness.healthy else 503
    if not readiness.healthy:
        log_event(
            "health_check_failed",
            level=logging.ERROR,
            status_code=status_code,
            check="database",
            check_status=readiness.status,
        )
    return JSONResponse(
        content=payload,
        status_code=status_code,
    )


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()
    return int(status)


def check_uptime(
    health_url: str,
    *,
    timeout_seconds: int = DEFAULT_HEALTH_TIMEOUT_SECONDS,
    opener: UrlOpener = urlopen,
) -> UptimeCheck:
    if timeout_seconds < 1:
        raise ValueError(
            "timeout_seconds must be at least 1."
        )
    try:
        safe_url = _safe_public_url(health_url)
    except ValueError:
        return UptimeCheck(
            healthy=False,
            status="invalid_url",
            status_code=None,
        )

    request = UrlRequest(
        safe_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "MARK-OS-Operations-Monitor/1.0",
        },
        method="GET",
    )
    try:
        with opener(
            request,
            timeout=timeout_seconds,
        ) as response:
            status_code = _response_status(response)
            body = response.read(
                _MAX_HEALTH_BODY_BYTES + 1
            )
    except HTTPError as exc:
        return UptimeCheck(
            healthy=False,
            status="http_error",
            status_code=int(exc.code),
        )
    except (URLError, TimeoutError, OSError):
        return UptimeCheck(
            healthy=False,
            status="unreachable",
            status_code=None,
        )

    if len(body) > _MAX_HEALTH_BODY_BYTES:
        return UptimeCheck(
            healthy=False,
            status="invalid_response",
            status_code=status_code,
        )
    try:
        payload = json.loads(
            body.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return UptimeCheck(
            healthy=False,
            status="invalid_response",
            status_code=status_code,
        )

    database_status = (
        payload.get("checks", {})
        .get("database", {})
        .get("status")
        if isinstance(payload, dict)
        else None
    )
    healthy = (
        status_code == 200
        and isinstance(payload, dict)
        and payload.get("status") == "ok"
        and database_status == "ok"
    )
    return UptimeCheck(
        healthy=healthy,
        status="ok" if healthy else "unhealthy_response",
        status_code=status_code,
    )


def _backup_check(
    status: BackupStatus,
) -> BackupCheck:
    if status.healthy:
        code = "ok"
    elif status.latest_backup_path is None:
        code = "missing"
    elif (
        status.age_hours is not None
        and status.age_hours > status.max_age_hours
    ):
        code = "stale"
    else:
        code = "invalid"

    return BackupCheck(
        healthy=status.healthy,
        status=code,
        age_hours=(
            round(status.age_hours, 2)
            if status.age_hours is not None
            else None
        ),
        max_age_hours=status.max_age_hours,
    )


def check_backup_visibility(
    backup_directory: str | Path,
    *,
    backup_prefix: str = "mark_os",
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> BackupCheck:
    return _backup_check(
        check_backup_status(
            backup_directory,
            backup_prefix=backup_prefix,
            max_age_hours=max_age_hours,
        )
    )


def _safe_alert_message(
    value: str,
) -> str:
    clean = " ".join(
        value.replace("\r", " ")
        .replace("\n", " ")
        .split()
    )
    return clean[:_MAX_ALERT_CHARACTERS]


def send_owner_alert(
    message: str,
    *,
    webhook_url: str | None = None,
    timeout_seconds: int = DEFAULT_HEALTH_TIMEOUT_SECONDS,
    opener: UrlOpener = urlopen,
) -> OwnerAlertDelivery:
    """Send one Discord-compatible webhook without logging its secret URL."""
    target = (
        webhook_url
        if webhook_url is not None
        else os.getenv(
            "MARK_OS_OWNER_ALERT_WEBHOOK_URL",
            "",
        )
    ).strip()
    if not target:
        return OwnerAlertDelivery(
            configured=False,
            delivered=False,
            status="not_configured",
        )
    if timeout_seconds < 1:
        raise ValueError(
            "timeout_seconds must be at least 1."
        )
    try:
        safe_target = _safe_public_url(target)
    except ValueError:
        log_event(
            "owner_alert_failed",
            level=logging.ERROR,
            channel="discord_webhook",
            failure="invalid_url",
        )
        return OwnerAlertDelivery(
            configured=True,
            delivered=False,
            status="invalid_url",
        )

    payload = json.dumps(
        {
            "content": _safe_alert_message(message),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = UrlRequest(
        safe_target,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "MARK-OS-Operations-Monitor/1.0",
        },
        method="POST",
    )
    try:
        with opener(
            request,
            timeout=timeout_seconds,
        ) as response:
            status_code = _response_status(response)
    except Exception as exc:
        log_exception(
            "owner_alert_failed",
            exc,
            channel="discord_webhook",
        )
        return OwnerAlertDelivery(
            configured=True,
            delivered=False,
            status="delivery_failed",
        )

    delivered = status_code in {200, 202, 204}
    log_event(
        (
            "owner_alert_delivered"
            if delivered
            else "owner_alert_failed"
        ),
        level=(
            logging.INFO
            if delivered
            else logging.ERROR
        ),
        channel="discord_webhook",
        status_code=status_code,
    )
    return OwnerAlertDelivery(
        configured=True,
        delivered=delivered,
        status=(
            "delivered"
            if delivered
            else "rejected"
        ),
    )


def _operations_alert_message(
    *,
    uptime: UptimeCheck,
    backup: BackupCheck,
    checked_at_utc: str,
) -> str:
    failures: list[str] = []
    if not uptime.healthy:
        failures.append(
            "Application health check failed."
        )
    if not backup.healthy:
        failures.append(
            "Database backup is missing, stale, or invalid."
        )
    return (
        "MARK-OS operations alert: "
        + " ".join(failures)
        + f" Checked at {checked_at_utc}."
    )


def run_operations_check(
    *,
    health_url: str,
    backup_directory: str | Path,
    backup_prefix: str = "mark_os",
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    timeout_seconds: int = DEFAULT_HEALTH_TIMEOUT_SECONDS,
    webhook_url: str | None = None,
    send_alert: bool = True,
    health_opener: UrlOpener = urlopen,
    alert_opener: UrlOpener = urlopen,
) -> OperationsCheck:
    checked_at = _utc_now().isoformat()
    uptime = check_uptime(
        health_url,
        timeout_seconds=timeout_seconds,
        opener=health_opener,
    )
    backup = check_backup_visibility(
        backup_directory,
        backup_prefix=backup_prefix,
        max_age_hours=max_age_hours,
    )
    healthy = uptime.healthy and backup.healthy

    if healthy or not send_alert:
        alert = OwnerAlertDelivery(
            configured=bool(
                (
                    webhook_url
                    if webhook_url is not None
                    else os.getenv(
                        "MARK_OS_OWNER_ALERT_WEBHOOK_URL",
                        "",
                    )
                ).strip()
            ),
            delivered=False,
            status=(
                "not_needed"
                if healthy
                else "suppressed"
            ),
        )
    else:
        alert = send_owner_alert(
            _operations_alert_message(
                uptime=uptime,
                backup=backup,
                checked_at_utc=checked_at,
            ),
            webhook_url=webhook_url,
            timeout_seconds=timeout_seconds,
            opener=alert_opener,
        )

    log_event(
        (
            "operations_check_succeeded"
            if healthy
            else "operations_check_failed"
        ),
        level=(
            logging.INFO
            if healthy
            else logging.ERROR
        ),
        uptime_status=uptime.status,
        uptime_status_code=uptime.status_code,
        backup_status=backup.status,
        backup_age_hours=backup.age_hours,
        alert_status=alert.status,
    )
    return OperationsCheck(
        healthy=healthy,
        checked_at_utc=checked_at,
        uptime=uptime,
        backup=backup,
        alert=alert,
    )


def operations_check_as_dict(
    result: OperationsCheck,
) -> dict[str, Any]:
    return asdict(result)
