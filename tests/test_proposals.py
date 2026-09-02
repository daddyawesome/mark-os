from __future__ import annotations

import pytest

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.leads import create_lead
from app.services.proposal_permissions import ProposalPermissionError
from app.services.proposals import (
    ProposalStateError,
    approve_proposal,
    create_proposal,
    get_proposal,
    list_proposals_for_lead,
    record_proposal_decision,
    send_proposal,
    submit_proposal_for_internal_review,
    update_proposal,
)
from app.services.relationship_manager import assign_relationship_manager
from app.services.team_users import create_relationship_manager


OWNER = {"id": 1, "username": "mark", "role": "owner"}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def proposal_database(tmp_path, monkeypatch):
    path = tmp_path / "proposals.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        junmar = create_relationship_manager(
            db,
            username="junmar",
            display_name="Junmar",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        lead = create_lead(
            db,
            company="Proposal Co",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="Referral",
            source_url="https://example.com/proposal",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="meeting",
            priority="medium",
            next_action="Prepare a proposal.",
            notes="",
            organization_id=organization_id,
        ).lead
        assign_relationship_manager(
            db,
            lead["id"],
            actor=OWNER,
            relationship_manager_user_id=junmar["id"],
            organization_id=organization_id,
        )

    return {
        "organization_id": organization_id,
        "lead_id": lead["id"],
        "junmar": dict(junmar),
    }


def _create_draft(db, organization_id, lead_id, **overrides):
    fields = {
        "actor": OWNER,
        "organization_id": organization_id,
        "lead_id": lead_id,
        "service_offered": "Data automation retainer",
        "engagement_type": "retainer",
    }
    fields.update(overrides)
    return create_proposal(db, **fields)


def test_owner_can_create_a_draft_proposal(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        proposal = _create_draft(db, organization_id, lead_id)

    assert proposal["status"] == "draft"
    assert proposal["decision_status"] is None
    assert proposal["service_offered"] == "Data automation retainer"


def test_relationship_manager_cannot_create_proposals(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]
    junmar = proposal_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        with pytest.raises(ProposalPermissionError):
            create_proposal(
                db,
                actor=junmar_actor,
                organization_id=organization_id,
                lead_id=lead_id,
                service_offered="Should fail",
            )


def test_full_lifecycle_draft_to_sent_to_accepted(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        proposal = _create_draft(
            db,
            organization_id,
            lead_id,
            proposed_price_amount_minor_units=5_000_00,
            proposal_url="https://docs.example.com/proposal-1",
        )

        reviewed = submit_proposal_for_internal_review(
            db,
            proposal["id"],
            actor=OWNER,
            organization_id=organization_id,
            expected_row_version=proposal["row_version"],
        )
        assert reviewed["status"] == "internal_review"

        approved = approve_proposal(
            db,
            proposal["id"],
            actor=OWNER,
            organization_id=organization_id,
            expected_row_version=reviewed["row_version"],
        )
        assert approved["status"] == "approved"
        assert approved["approved_by_user_id"] == OWNER["id"]

        sent = send_proposal(
            db,
            proposal["id"],
            actor=OWNER,
            organization_id=organization_id,
            expected_row_version=approved["row_version"],
        )
        assert sent["status"] == "sent"
        assert sent["proposal_sent_at"] is not None

        decided = record_proposal_decision(
            db,
            proposal["id"],
            actor=OWNER,
            decision="accepted",
            decision_reason="Client signed off.",
            organization_id=organization_id,
            expected_row_version=sent["row_version"],
        )
        assert decided["decision_status"] == "accepted"

        lead_after = db.execute(
            "SELECT pipeline_status FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()

    assert lead_after["pipeline_status"] == "meeting"


def test_cannot_skip_lifecycle_steps(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        proposal = _create_draft(db, organization_id, lead_id)

        with pytest.raises(ProposalStateError):
            approve_proposal(
                db,
                proposal["id"],
                actor=OWNER,
                organization_id=organization_id,
            )


def test_sending_requires_price_and_url(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        proposal = _create_draft(db, organization_id, lead_id)
        reviewed = submit_proposal_for_internal_review(
            db,
            proposal["id"],
            actor=OWNER,
            organization_id=organization_id,
        )
        approved = approve_proposal(
            db,
            proposal["id"],
            actor=OWNER,
            organization_id=organization_id,
        )

        with pytest.raises(ProposalStateError, match="price"):
            send_proposal(
                db,
                approved["id"],
                actor=OWNER,
                organization_id=organization_id,
            )


def test_cannot_edit_after_approval(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        proposal = _create_draft(
            db,
            organization_id,
            lead_id,
            proposed_price_amount_minor_units=1_000_00,
            proposal_url="https://docs.example.com/p2",
        )
        submit_proposal_for_internal_review(
            db, proposal["id"], actor=OWNER, organization_id=organization_id
        )
        approve_proposal(
            db, proposal["id"], actor=OWNER, organization_id=organization_id
        )

        with pytest.raises(ProposalStateError):
            update_proposal(
                db,
                proposal["id"],
                actor=OWNER,
                organization_id=organization_id,
                service_offered="Changed after approval",
            )


def test_decision_cannot_be_recorded_before_sent(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        proposal = _create_draft(db, organization_id, lead_id)

        with pytest.raises(ProposalStateError):
            record_proposal_decision(
                db,
                proposal["id"],
                actor=OWNER,
                decision="accepted",
                organization_id=organization_id,
            )


def test_decision_cannot_be_recorded_twice(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        proposal = _create_draft(
            db,
            organization_id,
            lead_id,
            proposed_price_amount_minor_units=1_000_00,
            proposal_url="https://docs.example.com/p3",
        )
        submit_proposal_for_internal_review(
            db, proposal["id"], actor=OWNER, organization_id=organization_id
        )
        approve_proposal(
            db, proposal["id"], actor=OWNER, organization_id=organization_id
        )
        sent = send_proposal(
            db, proposal["id"], actor=OWNER, organization_id=organization_id
        )
        record_proposal_decision(
            db,
            sent["id"],
            actor=OWNER,
            decision="rejected",
            organization_id=organization_id,
        )

        with pytest.raises(ProposalStateError):
            record_proposal_decision(
                db,
                sent["id"],
                actor=OWNER,
                decision="accepted",
                organization_id=organization_id,
            )


def test_invalid_decision_value_rejected(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        proposal = _create_draft(
            db,
            organization_id,
            lead_id,
            proposed_price_amount_minor_units=1_000_00,
            proposal_url="https://docs.example.com/p4",
        )
        submit_proposal_for_internal_review(
            db, proposal["id"], actor=OWNER, organization_id=organization_id
        )
        approve_proposal(
            db, proposal["id"], actor=OWNER, organization_id=organization_id
        )
        sent = send_proposal(
            db, proposal["id"], actor=OWNER, organization_id=organization_id
        )

        with pytest.raises(ValueError, match="Decision must be one of"):
            record_proposal_decision(
                db,
                sent["id"],
                actor=OWNER,
                decision="maybe",
                organization_id=organization_id,
            )


def test_negative_price_is_rejected(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        with pytest.raises(ValueError, match="cannot be negative"):
            _create_draft(
                db,
                organization_id,
                lead_id,
                proposed_price_amount_minor_units=-500,
            )


def test_list_and_get_proposals_for_lead(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        first = _create_draft(db, organization_id, lead_id)
        second = _create_draft(
            db,
            organization_id,
            lead_id,
            service_offered="Revised scope",
        )

        listed = list_proposals_for_lead(db, lead_id, organization_id=organization_id)
        fetched = get_proposal(db, first["id"], organization_id=organization_id)

    assert {row["id"] for row in listed} == {first["id"], second["id"]}
    assert fetched["id"] == first["id"]


def test_stale_row_version_is_rejected(proposal_database):
    organization_id = proposal_database["organization_id"]
    lead_id = proposal_database["lead_id"]

    with database.get_db() as db:
        proposal = _create_draft(db, organization_id, lead_id)

        with pytest.raises(ValueError, match="changed in another session"):
            update_proposal(
                db,
                proposal["id"],
                actor=OWNER,
                organization_id=organization_id,
                expected_row_version=999,
                service_offered="Stale attempt",
            )
