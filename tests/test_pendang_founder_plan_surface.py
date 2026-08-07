from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_pendang_shell_replaces_visible_mark_os_fieldbook_branding():
    base = _read("app/templates/base.html")

    assert "current_workspace.slug == 'pendang'" in base
    assert "<strong>PENDANG</strong>" in base
    assert "<small>Research &amp; Analytics</small>" in base
    assert "Pendang Research &amp; Analytics" in base

    # MARK OS Fieldbook remains available for MARK Agency/personal views,
    # but Pendang has its own conditional visible label.
    assert "MARK OS Fieldbook" in base
    assert (
        "{% if is_pendang_workspace %}\n"
        "                    Pendang Research &amp; Analytics"
    ) in base


def test_pendang_crm_contains_read_only_founder_plan():
    crm = _read("app/templates/client_hunting.html")

    assert "pendang-founder-plan" in crm
    assert "Founder Plan" in crm
    assert "Pendang Research &amp; Analytics" in crm

    for expected in (
        "Managing Director / Chief Statistical Officer",
        "Co-Founder / Chief Technology &amp; Data Officer",
        "Senior Statistical Consultant / Lead Researcher",
        "Research &amp; statistics",
        "Data analysis &amp; BI",
        "Data engineering &amp; automation",
        "Researchers &amp; universities",
        "Healthcare",
        "NGOs",
        "SMEs",
        "Leads → Clients → Projects → Payment → Referrals",
    ):
        assert expected in crm


def test_founder_plan_is_pendang_only_and_read_only():
    crm = _read("app/templates/client_hunting.html")

    marker = 'id="pendang-founder-plan"'
    assert marker in crm
    section = crm.split(marker, 1)[1].split("</section>", 1)[0]

    assert (
        "{% if current_workspace and current_workspace.slug == 'pendang' %}"
        in crm
    )
    assert "<form" not in section
    assert "<input" not in section
    assert "<textarea" not in section
    assert "contenteditable" not in section
