from __future__ import annotations

from pathlib import Path

from app.services.access_control import (
    can_access_request,
)


LEAD_SOURCER = {
    "id": 2,
    "username": "brother",
    "role": "lead_sourcer",
}


def test_lead_sourcer_can_access_research_edit_route():
    assert can_access_request(
        LEAD_SOURCER,
        "GET",
        "/crm/leads/12/research/edit",
    )
    assert can_access_request(
        LEAD_SOURCER,
        "HEAD",
        "/crm/leads/12/research/edit",
    )
    assert can_access_request(
        LEAD_SOURCER,
        "POST",
        "/crm/leads/12/research/edit",
    )


def test_lead_sourcer_still_cannot_use_owner_edit_routes():
    denied = (
        ("GET", "/crm/leads/12/edit"),
        ("POST", "/crm/leads/12/edit"),
        ("POST", "/crm/leads/12/pipeline"),
        (
            "POST",
            "/crm/leads/12/next-action",
        ),
        ("GET", "/crm/leads/12/delete"),
        ("POST", "/crm/leads/12/delete"),
    )

    assert not any(
        can_access_request(
            LEAD_SOURCER,
            method,
            path,
        )
        for method, path in denied
    )


def test_research_template_has_no_owner_control_inputs():
    root = Path(__file__).resolve().parent.parent
    template = (
        root
        / "app/templates/edit_lead_research.html"
    ).read_text(encoding="utf-8")

    assert 'name="company"' in template
    assert 'name="problem_opportunity"' in template
    assert 'name="next_action"' in template

    assert 'name="pipeline_status"' not in template
    assert 'name="priority"' not in template
    assert 'name="assigned_to_user_id"' not in template
    assert 'name="reviewed_by_user_id"' not in template
    assert (
        'name="outreach_approved_by_user_id"'
        not in template
    )
