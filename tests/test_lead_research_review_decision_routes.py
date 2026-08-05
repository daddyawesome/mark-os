from pathlib import Path

from app.services.access_control import (
    can_access_request,
)


OWNER = {
    "id": 1,
    "username": "mark",
    "role": "owner",
}

LEAD_SOURCER = {
    "id": 2,
    "username": "brother",
    "role": "lead_sourcer",
}


def test_owner_can_access_review_decision_route():
    assert can_access_request(
        OWNER,
        "POST",
        "/crm/leads/12/research/review",
    )


def test_sourcer_cannot_access_review_decision_route():
    assert not can_access_request(
        LEAD_SOURCER,
        "POST",
        "/crm/leads/12/research/review",
    )


def test_review_decision_has_no_get_surface():
    assert not can_access_request(
        LEAD_SOURCER,
        "GET",
        "/crm/leads/12/research/review",
    )


def test_owner_review_partial_has_three_decisions():
    root = Path(__file__).resolve().parent.parent
    partial = (
        root
        / "app/templates/partials/"
        "lead_research_review_panel.html"
    ).read_text(encoding="utf-8")

    assert 'value="approved"' in partial
    assert (
        'value="changes_requested"'
        in partial
    )
    assert 'value="rejected"' in partial
    assert 'name="review_notes"' in partial
    assert (
        "current_user.role == 'owner'"
        in partial
    )


def test_review_partial_does_not_approve_outreach():
    root = Path(__file__).resolve().parent.parent
    partial = (
        root
        / "app/templates/partials/"
        "lead_research_review_panel.html"
    ).read_text(encoding="utf-8")

    assert "/outreach" not in partial
    assert (
        'name="outreach_approved_by_user_id"'
        not in partial
    )


def test_lead_detail_includes_review_panel():
    root = Path(__file__).resolve().parent.parent
    detail = (
        root / "app/templates/lead_detail.html"
    ).read_text(encoding="utf-8")

    assert (
        '{% include "partials/'
        'lead_research_review_panel.html" %}'
        in detail
    )
