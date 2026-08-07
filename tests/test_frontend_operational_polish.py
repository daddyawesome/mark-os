from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(
        encoding="utf-8"
    )


def test_operational_ui_css_is_loaded_and_cache_busted():
    base = _read("app/templates/base.html")
    css = _read(
        "app/static/css/mark-os-frontend.css"
    )

    assert (
        "/static/css/mark-os-frontend.css?v=20260807-1"
        in base
    )
    assert (
        "MARK-OS operational UI baseline — 2026-08-07"
        in css
    )
    assert "body::before {\n    display: none;" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ":focus-visible" in css


def test_operational_ui_removes_glow_from_primary_surfaces():
    css = _read(
        "app/static/css/mark-os-frontend.css"
    )

    marker = (
        "/* MARK-OS operational UI baseline — 2026-08-07."
    )
    override = css.split(marker, 1)[1]

    assert ".mark-hero" in override
    assert "box-shadow: none;" in override
    assert ".mark-card" in override
    assert ".button.is-mark" in override
    assert "background: var(--mark-accent);" in override


def test_login_uses_shared_design_system_and_generic_copy():
    login = _read("app/templates/login.html")

    assert (
        "/static/css/mark-os-frontend.css?v=20260807-1"
        in login
    )
    assert "<style>" not in login
    assert '<body class="mark-login-page">' in login
    assert "Welcome back, Mark." not in login
    assert "Welcome back." in login
    assert "Private life data" not in login
    assert 'for="username"' in login
    assert 'id="username"' in login
    assert 'for="password"' in login
    assert 'id="password"' in login
    assert ">Sign in</button>" in login


def test_sidebar_brand_uses_product_not_release_jargon():
    base = _read("app/templates/base.html")

    assert "v0.4.0-family-workspaces" not in base
    assert "<small>Operating workspace</small>" in base


def test_crm_copy_is_shorter_and_operational():
    client = _read(
        "app/templates/client_hunting.html"
    )
    add_leads = _read(
        "app/templates/add_leads.html"
    )
    follow_up = _read(
        "app/templates/follow_up_command_center.html"
    )
    detail = _read(
        "app/templates/lead_detail.html"
    )

    assert "CRM · Opportunity pipeline" in client
    assert "Review leads and move the pipeline." in client
    assert "Research leads and submit clean work." in client

    assert "CRM · Lead intake" in add_leads
    assert ">Add leads.</h1>" in add_leads

    assert "CRM · Follow-up" in follow_up
    assert "See what needs follow-up." in follow_up

    assert "CRM · Lead {{ lead.id }}" in detail
    assert ">Pipeline</h2>" in detail
    assert ">Next action</h2>" in detail
