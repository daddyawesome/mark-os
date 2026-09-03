from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(
        encoding="utf-8"
    )


def test_client_hunting_hero_uses_responsive_layout_contract():
    template = _text(
        "app/templates/client_hunting.html"
    )

    assert (
        '<section class="mark-hero crm-hero p-6 mb-5">'
        in template
    )
    assert '<div class="crm-hero-layout">' in template
    assert '<div class="crm-hero-copy">' in template
    assert '<div class="crm-hero-actions">' in template
    assert '<div class="buttons crm-hero-buttons">' in template
    assert '<div class="crm-hero-count">' in template

    hero = template.split("</section>", 1)[0]
    assert "columns is-vcentered" not in hero
    assert 'class="column is-narrow"' not in hero


def test_follow_up_hero_uses_same_responsive_layout_contract():
    template = _text(
        "app/templates/follow_up_command_center.html"
    )

    assert (
        '<section class="mark-hero crm-hero p-6 mb-5">'
        in template
    )
    assert '<div class="crm-hero-layout">' in template
    assert '<div class="crm-hero-copy">' in template
    assert '<div class="crm-hero-actions">' in template
    assert '<div class="buttons crm-hero-buttons">' in template
    assert '<div class="crm-hero-count">' in template

    hero = template.split("</section>", 1)[0]
    assert "columns is-vcentered" not in hero
    assert 'class="column is-narrow"' not in hero


def test_crm_hero_css_prevents_word_collapse_and_is_cache_busted():
    css = _text(
        "app/static/css/mark-os-frontend.css"
    )
    base = _text(
        "app/templates/base.html"
    )

    required_rules = (
        ".crm-hero-layout",
        "grid-template-columns: minmax(0, 1fr);",
        ".crm-hero-copy .title",
        "overflow-wrap: normal;",
        "word-break: normal;",
        ".crm-hero-buttons",
        "@media (min-width: 1180px)",
        "@media (max-width: 640px)",
    )
    for rule in required_rules:
        assert rule in css

    assert (
        "/static/css/mark-os-frontend.css?v=20260904-1"
        in base
    )
