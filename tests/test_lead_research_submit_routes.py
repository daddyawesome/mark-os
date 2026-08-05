from pathlib import Path

from app.services.access_control import (
    can_access_request,
)


LEAD_SOURCER = {
    "id": 2,
    "username": "brother",
    "role": "lead_sourcer",
}


def test_sourcer_can_post_submit_for_review():
    assert can_access_request(
        LEAD_SOURCER,
        "POST",
        "/crm/leads/12/research/submit",
    )


def test_sourcer_cannot_open_owner_review_queue():
    assert not can_access_request(
        LEAD_SOURCER,
        "GET",
        "/crm/research-review",
    )


def test_submit_has_no_get_surface():
    assert not can_access_request(
        LEAD_SOURCER,
        "GET",
        "/crm/leads/12/research/submit",
    )


def test_detail_template_contains_controlled_submit_form():
    root = Path(__file__).resolve().parent.parent
    detail = (
        root / "app/templates/lead_detail.html"
    ).read_text(encoding="utf-8")

    assert '/research/submit"' in detail
    assert (
        "current_user.role == 'lead_sourcer'"
        in detail
    )
    assert "READY FOR REVIEW" in detail


def test_review_queue_is_read_only_in_this_phase():
    root = Path(__file__).resolve().parent.parent
    queue = (
        root
        / "app/templates/"
        "lead_research_review_queue.html"
    ).read_text(encoding="utf-8")

    assert "Owner Review Queue" in queue
    assert (
        'href="/crm/leads/{{ lead.id }}"'
        in queue
    )
    assert "/approve" not in queue
    assert "/request-changes" not in queue
    assert "/reject" not in queue
