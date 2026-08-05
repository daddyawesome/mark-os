from __future__ import annotations

import pytest

from app.services.lead_research_permissions import (
    LeadPermissionError,
    OWNER_GENERAL_EDIT_FIELDS,
    SOURCER_RESEARCH_EDIT_FIELDS,
    SYSTEM_MANAGED_FIELDS,
    can_approve_outreach,
    can_change_pipeline,
    can_edit_research,
    can_permanently_delete_lead,
    can_reassign_lead,
    can_review_research,
    can_soft_delete_lead,
    can_submit_for_review,
    can_transition_research_status,
    can_view_lead,
    can_view_private_finance,
    editable_fields_for,
    forbidden_edit_fields,
    require_edit_fields,
    require_pipeline_change,
    require_research_status_transition,
)


OWNER = {
    "id": 1,
    "username": "mark",
    "role": "owner",
}

BROTHER = {
    "id": 2,
    "username": "brother",
    "role": "lead_sourcer",
}

OTHER_SOURCER = {
    "id": 3,
    "username": "other",
    "role": "lead_sourcer",
}

MEMBER = {
    "id": 4,
    "username": "member",
    "role": "member",
}


def _lead(
    *,
    research_status: str = "draft",
    created_by_user_id: int | None = 2,
    assigned_to_user_id: int | None = 2,
    researched_by_user_id: int | None = 2,
    deleted_at: str | None = None,
):
    return {
        "id": 10,
        "created_by_user_id": created_by_user_id,
        "assigned_to_user_id": assigned_to_user_id,
        "researched_by_user_id": researched_by_user_id,
        "research_status": research_status,
        "pipeline_status": "new",
        "deleted_at": deleted_at,
    }


def test_owner_can_view_and_edit_active_lead():
    lead = _lead()

    assert can_view_lead(OWNER, lead)
    assert can_edit_research(OWNER, lead)
    assert (
        editable_fields_for(OWNER, lead)
        == OWNER_GENERAL_EDIT_FIELDS
    )


def test_sourcer_can_edit_related_work_in_editable_states():
    for status in (
        "draft",
        "researching",
        "changes_requested",
    ):
        lead = _lead(research_status=status)

        assert can_view_lead(BROTHER, lead)
        assert can_edit_research(BROTHER, lead)
        assert (
            editable_fields_for(BROTHER, lead)
            == SOURCER_RESEARCH_EDIT_FIELDS
        )


def test_sourcer_cannot_edit_approved_or_review_queue_lead():
    for status in (
        "ready_for_review",
        "approved",
        "rejected",
    ):
        lead = _lead(research_status=status)

        assert can_view_lead(BROTHER, lead)
        assert not can_edit_research(
            BROTHER,
            lead,
        )
        assert editable_fields_for(
            BROTHER,
            lead,
        ) == frozenset()


def test_unrelated_sourcer_cannot_view_or_edit_lead():
    lead = _lead()

    assert not can_view_lead(
        OTHER_SOURCER,
        lead,
    )
    assert not can_edit_research(
        OTHER_SOURCER,
        lead,
    )


def test_created_assigned_or_researched_relationship_grants_view():
    created = _lead(
        assigned_to_user_id=1,
        researched_by_user_id=1,
    )
    assigned = _lead(
        created_by_user_id=1,
        researched_by_user_id=1,
    )
    researched = _lead(
        created_by_user_id=1,
        assigned_to_user_id=1,
    )

    assert can_view_lead(BROTHER, created)
    assert can_view_lead(BROTHER, assigned)
    assert can_view_lead(BROTHER, researched)


def test_deleted_lead_is_not_editable_or_visible():
    lead = _lead(
        deleted_at="2026-08-05 12:00:00",
    )

    for user in (OWNER, BROTHER):
        assert not can_view_lead(user, lead)
        assert not can_edit_research(user, lead)
        assert not can_soft_delete_lead(
            user,
            lead,
        )


def test_sourcer_field_allowlist_blocks_owner_and_system_fields():
    lead = _lead()

    allowed = {
        "company",
        "problem_opportunity",
        "notes",
    }
    assert require_edit_fields(
        BROTHER,
        lead,
        allowed,
    ) == frozenset(allowed)

    forbidden = forbidden_edit_fields(
        BROTHER,
        lead,
        {
            "company",
            "priority",
            "pipeline_status",
            "reviewed_by_user_id",
        },
    )
    assert forbidden == {
        "priority",
        "pipeline_status",
        "reviewed_by_user_id",
    }

    with pytest.raises(
        LeadPermissionError,
        match="not allowed",
    ):
        require_edit_fields(
            BROTHER,
            lead,
            {
                "company",
                "priority",
            },
        )


def test_system_managed_fields_are_not_general_edit_fields():
    assert (
        SYSTEM_MANAGED_FIELDS
        & SOURCER_RESEARCH_EDIT_FIELDS
        == frozenset()
    )
    assert (
        SYSTEM_MANAGED_FIELDS
        & OWNER_GENERAL_EDIT_FIELDS
        == frozenset()
    )


def test_sourcer_research_transitions_are_controlled():
    draft = _lead(research_status="draft")
    researching = _lead(
        research_status="researching"
    )
    changes = _lead(
        research_status="changes_requested"
    )

    assert can_transition_research_status(
        BROTHER,
        draft,
        "researching",
    )
    assert can_submit_for_review(
        BROTHER,
        draft,
    )
    assert can_submit_for_review(
        BROTHER,
        researching,
    )
    assert can_transition_research_status(
        BROTHER,
        changes,
        "researching",
    )
    assert can_submit_for_review(
        BROTHER,
        changes,
    )

    assert not can_transition_research_status(
        BROTHER,
        draft,
        "approved",
    )
    assert not can_transition_research_status(
        BROTHER,
        researching,
        "rejected",
    )


def test_owner_controls_review_and_outreach_approval():
    ready = _lead(
        research_status="ready_for_review"
    )
    approved = _lead(
        research_status="approved"
    )

    assert can_review_research(OWNER, ready)
    assert not can_review_research(
        BROTHER,
        ready,
    )
    assert can_approve_outreach(
        OWNER,
        approved,
    )
    assert not can_approve_outreach(
        BROTHER,
        approved,
    )


def test_owner_controls_pipeline_reassignment_and_soft_delete():
    lead = _lead(
        research_status="approved"
    )

    assert can_change_pipeline(
        OWNER,
        lead,
        "contacted",
    )
    assert not can_change_pipeline(
        BROTHER,
        lead,
        "contacted",
    )
    assert can_reassign_lead(OWNER, lead)
    assert not can_reassign_lead(
        BROTHER,
        lead,
    )
    assert can_soft_delete_lead(OWNER, lead)
    assert not can_soft_delete_lead(
        BROTHER,
        lead,
    )


def test_permanent_delete_is_unavailable_to_every_role():
    lead = _lead()

    assert not can_permanently_delete_lead(
        OWNER,
        lead,
    )
    assert not can_permanently_delete_lead(
        BROTHER,
        lead,
    )


def test_private_finance_is_owner_only():
    assert can_view_private_finance(OWNER)
    assert not can_view_private_finance(
        BROTHER
    )
    assert not can_view_private_finance(
        MEMBER
    )


def test_member_and_unknown_role_have_no_crm_policy_access():
    lead = _lead()
    unknown = {
        "id": 9,
        "role": "administrator",
    }

    for user in (MEMBER, unknown, None):
        assert not can_view_lead(user, lead)
        assert not can_edit_research(
            user,
            lead,
        )
        assert not can_submit_for_review(
            user,
            lead,
        )
        assert not can_review_research(
            user,
            lead,
        )
        assert not can_approve_outreach(
            user,
            lead,
        )


def test_require_helpers_reject_invalid_or_forbidden_actions():
    lead = _lead()

    with pytest.raises(
        ValueError,
        match="Unsupported research status",
    ):
        require_research_status_transition(
            BROTHER,
            lead,
            "published",
        )

    with pytest.raises(
        LeadPermissionError,
        match="not allowed",
    ):
        require_research_status_transition(
            BROTHER,
            lead,
            "approved",
        )

    with pytest.raises(
        ValueError,
        match="Unsupported lead pipeline",
    ):
        require_pipeline_change(
            OWNER,
            lead,
            "qualified",
        )

    with pytest.raises(
        LeadPermissionError,
        match="Only the Owner",
    ):
        require_pipeline_change(
            BROTHER,
            lead,
            "contacted",
        )


def test_empty_field_update_is_rejected():
    with pytest.raises(
        ValueError,
        match="At least one",
    ):
        require_edit_fields(
            OWNER,
            _lead(),
            set(),
        )
