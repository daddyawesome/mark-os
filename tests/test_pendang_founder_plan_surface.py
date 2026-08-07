from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_pendang_shell_recognizes_company_home_as_pendang_workspace():
    base = _read("app/templates/base.html")

    assert "request.url.path.startswith('/pendang')" in base
    assert "<strong>PENDANG</strong>" in base
    assert "<small>Research &amp; Analytics</small>" in base
    assert "Pendang Research &amp; Analytics" in base
    assert "sidebar_home" in base


def test_pendang_company_home_contains_canonical_sections_and_edit_controls():
    company = _read("app/templates/pendang_company.html")
    service = _read("app/services/pendang_company.py")

    for expected in (
        "Founder Plan",
        "About Pendang",
        "Company CV",
    ):
        assert expected in company

    assert "{{ section.title }}" in company
    for expected in (
        "Services & Pricing",
        "Historical Projects",
        "Case Studies",
        "Warm Relationships",
        "Content Studio",
        "Meeting Preparation",
        "Shared Company Documents",
    ):
        assert expected in service

    assert 'action="/pendang/profile"' in company
    assert 'action="/pendang/items"' in company
    assert "row_version" in company
    assert "{% if can_manage %}" in company
    assert "does not generate AI content or publish externally" in service
    assert "does not upload file bytes" in service

def test_crm_links_to_company_home_instead_of_embedding_static_founder_plan():
    crm = _read("app/templates/client_hunting.html")

    assert 'href="/pendang"' in crm
    assert 'id="pendang-founder-plan"' not in crm
