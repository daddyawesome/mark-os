from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.error import URLError

from app.routes import pages
from app.services.database_backup import (
    create_sqlite_backup,
)
from app.services.operations_monitoring import (
    build_health_response,
    check_database_readiness,
    check_uptime,
    run_operations_check,
    send_owner_alert,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status: int,
        body: bytes = b"",
    ) -> None:
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:
        return None

    def read(
        self,
        size: int = -1,
    ) -> bytes:
        if size < 0:
            return self._body
        return self._body[:size]

    def getcode(self) -> int:
        return self.status


def _create_database(path: Path) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE
        )
        """
    )
    connection.execute(
        """
        INSERT INTO users (username)
        VALUES ('mark')
        """
    )
    connection.commit()
    connection.close()


def _healthy_body() -> bytes:
    return json.dumps(
        {
            "status": "ok",
            "version": "0.5.0-observability",
            "checks": {
                "database": {
                    "status": "ok",
                }
            },
        }
    ).encode("utf-8")


def test_database_readiness_is_read_only_and_generic(
    tmp_path: Path,
):
    missing = tmp_path / "missing.db"
    missing_result = check_database_readiness(
        missing
    )
    assert missing_result.healthy is False
    assert missing_result.status == "unavailable"
    assert missing.exists() is False

    database_path = tmp_path / "ready.db"
    _create_database(database_path)
    ready = check_database_readiness(
        database_path
    )
    assert ready.healthy is True
    assert ready.status == "ok"


def test_health_response_is_database_aware_without_paths(
    tmp_path: Path,
):
    database_path = tmp_path / "health.db"
    _create_database(database_path)

    healthy = build_health_response(
        database_path
    )
    healthy_payload = json.loads(
        healthy.body
    )
    assert healthy.status_code == 200
    assert healthy_payload == {
        "status": "ok",
        "version": "0.5.0-observability",
        "checks": {
            "database": {
                "status": "ok",
            }
        },
    }

    missing_path = tmp_path / "private-name.db"
    unavailable = build_health_response(
        missing_path
    )
    unavailable_text = unavailable.body.decode(
        "utf-8"
    )
    assert unavailable.status_code == 503
    assert "private-name.db" not in unavailable_text
    assert json.loads(unavailable.body)[
        "checks"
    ]["database"]["status"] == "unavailable"


def test_pages_health_uses_current_database_path(
    tmp_path: Path,
    monkeypatch,
):
    database_path = tmp_path / "route-health.db"
    _create_database(database_path)
    monkeypatch.setattr(
        pages.database,
        "DB_PATH",
        database_path,
    )

    response = pages.health()
    assert response.status_code == 200
    assert json.loads(response.body)[
        "checks"
    ]["database"]["status"] == "ok"


def test_uptime_check_accepts_only_healthy_database_payload():
    def healthy_opener(
        request,
        *,
        timeout,
    ):
        assert request.full_url == (
            "https://mark-os.example/health"
        )
        assert timeout == 7
        return FakeResponse(
            status=200,
            body=_healthy_body(),
        )

    healthy = check_uptime(
        "https://mark-os.example/health?ignored=1",
        timeout_seconds=7,
        opener=healthy_opener,
    )
    assert healthy.healthy is True
    assert healthy.status == "ok"
    assert healthy.status_code == 200

    def degraded_opener(
        request,
        *,
        timeout,
    ):
        return FakeResponse(
            status=200,
            body=json.dumps(
                {
                    "status": "unavailable",
                    "checks": {
                        "database": {
                            "status": "unavailable",
                        }
                    },
                }
            ).encode("utf-8"),
        )

    degraded = check_uptime(
        "https://mark-os.example/health",
        opener=degraded_opener,
    )
    assert degraded.healthy is False
    assert degraded.status == "unhealthy_response"


def test_uptime_check_fails_closed_on_invalid_or_unreachable_url():
    invalid = check_uptime(
        "file:///private/database",
    )
    assert invalid.healthy is False
    assert invalid.status == "invalid_url"

    def unreachable_opener(
        request,
        *,
        timeout,
    ):
        raise URLError(
            "private network detail"
        )

    unreachable = check_uptime(
        "https://mark-os.example/health",
        opener=unreachable_opener,
    )
    assert unreachable.healthy is False
    assert unreachable.status == "unreachable"
    assert unreachable.status_code is None


def test_owner_alert_is_optional_and_discord_compatible(
    monkeypatch,
):
    monkeypatch.delenv(
        "MARK_OS_OWNER_ALERT_WEBHOOK_URL",
        raising=False,
    )
    disabled = send_owner_alert(
        "MARK-OS alert"
    )
    assert disabled.configured is False
    assert disabled.status == "not_configured"

    requests = []

    def alert_opener(
        request,
        *,
        timeout,
    ):
        requests.append(request)
        return FakeResponse(
            status=204,
        )

    delivered = send_owner_alert(
        "MARK-OS alert\nDatabase backup failed.",
        webhook_url=(
            "https://discord.example/api/webhooks/"
            "private-token?secret=ignored"
        ),
        opener=alert_opener,
    )
    assert delivered.configured is True
    assert delivered.delivered is True
    assert delivered.status == "delivered"
    assert len(requests) == 1
    request = requests[0]
    assert request.full_url == (
        "https://discord.example/api/webhooks/"
        "private-token"
    )
    assert request.get_method() == "POST"
    payload = json.loads(
        request.data.decode("utf-8")
    )
    assert payload == {
        "content": (
            "MARK-OS alert Database backup failed."
        )
    }


def test_operations_check_healthy_does_not_send_alert(
    tmp_path: Path,
):
    source = tmp_path / "mark-os.db"
    backup_directory = tmp_path / "backups"
    _create_database(source)
    create_sqlite_backup(
        source,
        backup_directory,
    )

    alert_calls = []

    def health_opener(
        request,
        *,
        timeout,
    ):
        return FakeResponse(
            status=200,
            body=_healthy_body(),
        )

    def alert_opener(
        request,
        *,
        timeout,
    ):
        alert_calls.append(request)
        return FakeResponse(
            status=204,
        )

    result = run_operations_check(
        health_url=(
            "https://mark-os.example/health"
        ),
        backup_directory=backup_directory,
        webhook_url=(
            "https://discord.example/api/webhooks/token"
        ),
        health_opener=health_opener,
        alert_opener=alert_opener,
    )
    assert result.healthy is True
    assert result.uptime.status == "ok"
    assert result.backup.status == "ok"
    assert result.alert.status == "not_needed"
    assert alert_calls == []


def test_operations_check_sends_one_generic_alert_on_combined_failure(
    tmp_path: Path,
):
    alert_requests = []

    def unhealthy_opener(
        request,
        *,
        timeout,
    ):
        return FakeResponse(
            status=503,
            body=b'{"status":"unavailable"}',
        )

    def alert_opener(
        request,
        *,
        timeout,
    ):
        alert_requests.append(request)
        return FakeResponse(
            status=204,
        )

    private_backup_path = (
        tmp_path
        / "private-customer-backups"
    )
    result = run_operations_check(
        health_url=(
            "https://mark-os.example/health"
        ),
        backup_directory=private_backup_path,
        webhook_url=(
            "https://discord.example/api/webhooks/"
            "private-token"
        ),
        health_opener=unhealthy_opener,
        alert_opener=alert_opener,
    )
    assert result.healthy is False
    assert result.uptime.healthy is False
    assert result.backup.status == "missing"
    assert result.alert.delivered is True
    assert len(alert_requests) == 1

    message = json.loads(
        alert_requests[0].data.decode("utf-8")
    )["content"]
    assert "Application health check failed." in message
    assert (
        "Database backup is missing, stale, or invalid."
        in message
    )
    assert "private-customer-backups" not in message
    assert "private-token" not in message
