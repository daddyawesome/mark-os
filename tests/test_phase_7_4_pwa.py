from __future__ import annotations

import json
from pathlib import Path

from fastapi import Request

from app import database
from app.routes import checkins
from app.services.team_users import get_primary_owner_id


ROOT = Path(__file__).resolve().parents[1]


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/check-in",
            "raw_path": b"/check-in",
            "headers": [(b"hx-request", b"true")],
            "query_string": b"",
            "scheme": "https",
            "server": ("example.test", 443),
            "client": ("testclient", 50000),
        }
    )


def test_checkin_retry_key_is_idempotent_and_preserves_xp(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "pwa-retry.db")
    _configure_owner(monkeypatch)
    database.init_db()
    database.init_db()
    with database.get_db() as db:
        owner_id = get_primary_owner_id(db, active_only=True)
        before_game = [tuple(row) for row in db.execute("SELECT * FROM game_state")]
    monkeypatch.setattr(checkins, "request_user_id", lambda request: owner_id)

    for _ in range(2):
        response = checkins.create_checkin(
            _request(),
            cash_in=100,
            expenses=10,
            free_hours=2,
            energy=4,
            accomplished="PWA draft",
            blocker="",
            notes="Retry safely",
            request_key="offline-draft-fixed-key",
        )
        assert response.status_code == 200

    with database.get_db() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM checkins WHERE request_key = ?",
            ("offline-draft-fixed-key",),
        ).fetchone()[0]
        directions = db.execute(
            """
            SELECT COUNT(*) FROM directions
            WHERE checkin_id = (SELECT id FROM checkins WHERE request_key = ?)
            """,
            ("offline-draft-fixed-key",),
        ).fetchone()[0]
        after_game = [tuple(row) for row in db.execute("SELECT * FROM game_state")]
    assert count == 1
    assert directions == 1
    assert after_game == before_game


def test_manifest_and_service_worker_keep_authenticated_html_out_of_cache():
    manifest = json.loads((ROOT / "app/static/manifest.webmanifest").read_text())
    worker = (ROOT / "app/static/service-worker.js").read_text()
    assert manifest["display"] == "standalone"
    assert {icon["sizes"] for icon in manifest["icons"]} == {"192x192", "512x512"}
    assert 'event.request.method !== "GET"' in worker
    assert 'event.request.mode === "navigate"' in worker
    assert "cache.put" not in worker
    assert 'caches.match("/static/offline.html")' in worker
    assert 'url.pathname.startsWith("/static/")' in worker


def test_offline_checkin_draft_requires_explicit_retry_and_keeps_form_fallback():
    script = (ROOT / "app/static/js/mark-pwa.js").read_text()
    template = (ROOT / "app/templates/index.html").read_text()
    assert 'method="post" action="/check-in"' in template
    assert 'hx-post="/check-in"' in template
    assert "localStorage.setItem" in script
    assert "event.preventDefault()" in script
    assert "Back online. Review the draft, then submit." in script
    assert "form.submit()" not in script
