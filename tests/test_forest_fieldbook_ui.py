from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_forest_fieldbook_css_tokens_and_marker_exist():
    css = _read("app/static/css/mark-os-frontend.css")

    assert "MARK-OS Forest Fieldbook" in css
    for token in (
        "--field-paper: #f3f0df;",
        "--field-ink: #203428;",
        "--field-pine: #173c2a;",
        "--field-moss: #668052;",
        "--field-fern: #93aa71;",
        "--field-shadow: #183624;",
    ):
        assert token in css

    assert "box-shadow: 6px 6px 0" in css
    assert ".fieldbook-metrics" in css
    assert ".fieldbook-context" in css


def test_fieldbook_keeps_operational_data_unrotated():
    css = _read("app/static/css/mark-os-frontend.css")
    fieldbook = css.split("/* MARK-OS Forest Fieldbook", 1)[1]

    assert ".fieldbook-metrics .fieldbook-metric-card" in fieldbook
    assert ".table" in fieldbook
    assert ".input," in fieldbook
    assert "transform: rotate" in fieldbook

    table_block = fieldbook.split(".table {", 1)[1].split("}", 1)[0]
    input_block = fieldbook.split(".input,", 1)[1].split("}", 1)[0]
    assert "rotate(" not in table_block
    assert "rotate(" not in input_block


def test_base_renders_read_only_fieldbook_workspace_context():
    base = _read("app/templates/base.html")

    assert "{% set current_workspace = request.state.current_workspace %}" in base
    assert 'class="fieldbook-context"' in base
    assert "MARK OS Fieldbook" in base
    assert "Business workspace" in base
    assert "{{ current_workspace.name if current_workspace else 'Pending workspace' }}" in base
    assert "Personal workspace" in base

    context = base.split('<header\n            class="fieldbook-context"', 1)[1].split("</header>", 1)[0]
    assert 'action="/workspace/select"' in context
    assert 'name="organization_id"' in context
    assert "current_user.role == 'owner'" in context
    assert "authorized_workspaces|length > 1" in context


def test_crm_metrics_use_sticky_note_fieldbook_classes():
    crm = _read("app/templates/client_hunting.html")
    queues = _read("app/templates/partials/crm_role_queues.html")
    follow_up = _read("app/templates/follow_up_command_center.html")

    assert 'class="columns is-multiline mb-5 fieldbook-metrics"' in crm
    assert "fieldbook-metric-card" in crm
    assert "fieldbook-queue-grid" in queues
    assert "fieldbook-queue-card" in queues
    assert 'class="fieldbook-queue-stack"' in follow_up


def test_fieldbook_cache_bust_is_consistent():
    base = _read("app/templates/base.html")
    login = _read("app/templates/login.html")

    expected = "/static/css/mark-os-frontend.css?v=20260807-2"
    assert expected in base
    assert expected in login


def test_fieldbook_design_contract_and_attribution_are_recorded():
    design = _read(".agents/skills/mark-os-ui/DESIGN.md")
    notice = _read("THIRD_PARTY_NOTICES.md")

    assert "Forest Fieldbook visual system" in design
    assert "Orbit-inspired Forest Fieldbook" in design
    assert "MARK-OS remains FastAPI + Jinja + HTMX + Bulma +" in design

    assert "Orbit — design inspiration" in notice
    assert "https://github.com/nvkhuy/orbit" in notice
    assert "License: MIT" in notice
