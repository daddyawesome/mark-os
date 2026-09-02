from __future__ import annotations

import pytest

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.lead_activities import (
    LeadActivityPermissionError,
    create_activity,
)
from app.services.lead_pipeline_workflow import (
    approve_outreach,
    change_pipeline_stage,
)
from app.services.lead_research_permissions import (
    LeadPermissionError,
    can_change_pipeline,
    can_perform_delegated_contact,
)
from app.services.lead_research_workflow import (
    review_research,
    submit_research_for_review,
)
from app.services.leads import create_lead
from app.services.team_users import (
    create_lead_sourcer,
    create_relationship_manager,
    get_primary_owner_id,
    set_can_contact_leads,
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _contact_payload(responsible_user_id: int) -> dict:
    return {
        "contact_activity_type": "email_sent",
        "contact_activity_at": "2026-09-06T19:30",
        "contact_channel": "email",
        "contact_message_summary": "Sent the Owner-approved first introduction.",
        "contact_notes": "Used the approved outreach wording.",
        "contact_responsible_user_id": responsible_user_id,
        "contact_response_status": "awaiting_reply",
        "contact_next_follow_up_date": "2026-09-09",
    }


@pytest.fixture
def delegated_context(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "delegated-outreach.db")
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        owner_id = get_primary_owner_id(db)
        owner = dict(
            db.execute(
                "SELECT id, username, display_name, role, active FROM users WHERE id = ?",
                (owner_id,),
            ).fetchone()
        )
        sourcer = dict(
            create_lead_sourcer(
                db,
                username="delegated-researcher",
                display_name="Researcher",
                password="temporary-pass-123",
                password_confirmation="temporary-pass-123",
            )
        )
        manager = dict(
            create_relationship_manager(
                db,
                username="delegated-manager",
                display_name="Delegated Manager",
                password="temporary-pass-456",
                password_confirmation="temporary-pass-456",
            )
        )
        other_manager = dict(
            create_relationship_manager(
                db,
                username="other-manager",
                display_name="Other Manager",
                password="temporary-pass-789",
                password_confirmation="temporary-pass-789",
            )
        )

        def _approved_lead(company: str) -> dict:
            lead = create_lead(
                db,
                company=company,
                contact_person="Alex Buyer",
                job_title="Founder",
                source="LinkedIn",
                source_url=f"https://example.com/{company.casefold().replace(' ', '-')}",
                problem_opportunity="First-contact history is fragmented.",
                why_mark_fits="Mark can build an auditable workflow.",
                pipeline_status="new",
                priority="high",
                next_action="Complete research approval.",
                notes="",
                created_by_user_id=sourcer["id"],
                assigned_to_user_id=owner["id"],
                business_development_owner_user_id=manager["id"],
                organization_id=organization_id,
            ).lead
            submitted = submit_research_for_review(
                db, lead["id"], actor=sourcer, organization_id=organization_id
            )
            reviewed = review_research(
                db,
                submitted["id"],
                actor=owner,
                decision="approved",
                review_notes="Verified.",
                organization_id=organization_id,
            )
            approved = approve_outreach(
                db, reviewed["id"], actor=owner, organization_id=organization_id
            )
            return dict(approved)

        approved_lead = _approved_lead("Delegated Contact Co")

    return {
        "organization_id": organization_id,
        "owner": owner,
        "sourcer": sourcer,
        "manager": manager,
        "other_manager": other_manager,
        "lead": approved_lead,
    }


def test_grant_lets_delegated_rm_perform_contacted_transition(delegated_context):
    organization_id = delegated_context["organization_id"]
    manager = delegated_context["manager"]
    lead = delegated_context["lead"]
    manager_actor = {"id": manager["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        set_can_contact_leads(
            db,
            target_user_id=manager["id"],
            acting_user_id=delegated_context["owner"]["id"],
            workspace_slug="mark-agency",
            can_contact_leads=True,
        )

        contacted = change_pipeline_stage(
            db,
            lead["id"],
            actor=manager_actor,
            pipeline_status="contacted",
            organization_id=organization_id,
            expected_row_version=lead["row_version"],
            **_contact_payload(manager["id"]),
        )

    assert contacted["pipeline_status"] == "contacted"

    with database.get_db() as db:
        activity = db.execute(
            "SELECT performed_by_user_id, activity_type FROM lead_activities "
            "WHERE lead_id = ?",
            (lead["id"],),
        ).fetchone()
    assert activity["performed_by_user_id"] == manager["id"]
    assert activity["activity_type"] == "email_sent"


def test_without_grant_delegated_rm_is_denied(delegated_context):
    organization_id = delegated_context["organization_id"]
    manager = delegated_context["manager"]
    lead = delegated_context["lead"]
    manager_actor = {"id": manager["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        with pytest.raises(LeadPermissionError):
            change_pipeline_stage(
                db,
                lead["id"],
                actor=manager_actor,
                pipeline_status="contacted",
                organization_id=organization_id,
                **_contact_payload(manager["id"]),
            )


def test_grant_does_not_extend_to_a_different_managers_lead(delegated_context):
    organization_id = delegated_context["organization_id"]
    manager = delegated_context["manager"]
    other_manager = delegated_context["other_manager"]
    owner = delegated_context["owner"]
    sourcer = delegated_context["sourcer"]

    with database.get_db() as db:
        set_can_contact_leads(
            db,
            target_user_id=manager["id"],
            acting_user_id=owner["id"],
            workspace_slug="mark-agency",
            can_contact_leads=True,
        )

        other_lead = create_lead(
            db,
            company="Other Manager Co",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="LinkedIn",
            source_url="https://example.com/other-manager-co",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="new",
            priority="medium",
            next_action="Research.",
            notes="",
            created_by_user_id=sourcer["id"],
            assigned_to_user_id=owner["id"],
            business_development_owner_user_id=other_manager["id"],
            organization_id=organization_id,
        ).lead
        submitted = submit_research_for_review(
            db, other_lead["id"], actor=sourcer, organization_id=organization_id
        )
        reviewed = review_research(
            db,
            submitted["id"],
            actor=owner,
            decision="approved",
            review_notes="Verified.",
            organization_id=organization_id,
        )
        approve_outreach(db, reviewed["id"], actor=owner, organization_id=organization_id)

        manager_actor = {"id": manager["id"], "role": "relationship_manager"}
        with pytest.raises(LeadPermissionError):
            change_pipeline_stage(
                db,
                other_lead["id"],
                actor=manager_actor,
                pipeline_status="contacted",
                organization_id=organization_id,
                **_contact_payload(manager["id"]),
            )


def test_grant_does_not_unlock_other_pipeline_transitions(delegated_context):
    """No privilege escalation: only 'contacted' is reachable, nothing else."""
    organization_id = delegated_context["organization_id"]
    manager = delegated_context["manager"]
    lead = delegated_context["lead"]
    manager_actor = {"id": manager["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        set_can_contact_leads(
            db,
            target_user_id=manager["id"],
            acting_user_id=delegated_context["owner"]["id"],
            workspace_slug="mark-agency",
            can_contact_leads=True,
        )

        for forbidden_target in ("reviewed", "meeting", "proposal", "won", "lost"):
            with pytest.raises(LeadPermissionError):
                change_pipeline_stage(
                    db,
                    lead["id"],
                    actor=manager_actor,
                    pipeline_status=forbidden_target,
                    organization_id=organization_id,
                )


def test_revocation_takes_effect_on_the_next_check(delegated_context):
    organization_id = delegated_context["organization_id"]
    manager = delegated_context["manager"]
    lead = delegated_context["lead"]
    owner = delegated_context["owner"]
    manager_actor = {"id": manager["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        set_can_contact_leads(
            db,
            target_user_id=manager["id"],
            acting_user_id=owner["id"],
            workspace_slug="mark-agency",
            can_contact_leads=True,
        )
        set_can_contact_leads(
            db,
            target_user_id=manager["id"],
            acting_user_id=owner["id"],
            workspace_slug="mark-agency",
            can_contact_leads=False,
        )

        with pytest.raises(LeadPermissionError):
            change_pipeline_stage(
                db,
                lead["id"],
                actor=manager_actor,
                pipeline_status="contacted",
                organization_id=organization_id,
                **_contact_payload(manager["id"]),
            )


def test_only_owner_can_grant_the_permission(delegated_context):
    manager = delegated_context["manager"]
    other_manager = delegated_context["other_manager"]

    with database.get_db() as db:
        with pytest.raises(ValueError, match="active global Owner"):
            set_can_contact_leads(
                db,
                target_user_id=manager["id"],
                acting_user_id=other_manager["id"],
                workspace_slug="mark-agency",
                can_contact_leads=True,
            )


def test_permission_cannot_be_granted_to_non_relationship_manager(
    delegated_context,
):
    sourcer = delegated_context["sourcer"]
    owner = delegated_context["owner"]

    with database.get_db() as db:
        with pytest.raises(ValueError, match="Relationship Manager"):
            set_can_contact_leads(
                db,
                target_user_id=sourcer["id"],
                acting_user_id=owner["id"],
                workspace_slug="mark-agency",
                can_contact_leads=True,
            )


def test_delegated_rm_gets_only_contact_activity_types(delegated_context):
    organization_id = delegated_context["organization_id"]
    manager = delegated_context["manager"]
    lead = delegated_context["lead"]
    owner = delegated_context["owner"]
    manager_actor = {"id": manager["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        set_can_contact_leads(
            db,
            target_user_id=manager["id"],
            acting_user_id=owner["id"],
            workspace_slug="mark-agency",
            can_contact_leads=True,
        )

        # Allowed: one of CONTACT_ACTIVITY_TYPES, on their own lead.
        create_activity(
            db,
            lead["id"],
            actor=manager_actor,
            activity_type="follow_up_sent",
            activity_at="2026-09-07T10:00",
            channel="email",
            message_summary="Sent a follow-up.",
            performed_by_user_id=manager["id"],
            organization_id=organization_id,
        )

        # Denied: not a contact-outreach activity type.
        with pytest.raises(LeadActivityPermissionError):
            create_activity(
                db,
                lead["id"],
                actor=manager_actor,
                activity_type="research_started",
                activity_at="2026-09-07T10:05",
                channel="internal",
                message_summary="Should be denied.",
                performed_by_user_id=manager["id"],
                organization_id=organization_id,
            )


def test_can_perform_delegated_contact_helper(delegated_context):
    manager = delegated_context["manager"]
    lead = delegated_context["lead"]
    manager_actor_without_flag = {
        "id": manager["id"],
        "role": "relationship_manager",
        "can_contact_leads": False,
    }
    manager_actor_with_flag = {
        "id": manager["id"],
        "role": "relationship_manager",
        "can_contact_leads": True,
    }

    assert can_perform_delegated_contact(manager_actor_without_flag, lead) is False
    assert can_perform_delegated_contact(manager_actor_with_flag, lead) is True
    assert (
        can_change_pipeline(manager_actor_with_flag, lead, "contacted") is True
    )
    assert can_change_pipeline(manager_actor_with_flag, lead, "won") is False
