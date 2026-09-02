from __future__ import annotations

import pytest

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.lead_qualification_permissions import (
    LeadQualificationPermissionError,
    can_decide_qualification,
    can_edit_qualification,
)
from app.services.lead_qualification_workflow import (
    decide_qualification,
    update_qualification_details,
)
from app.services.leads import create_lead
from app.services.relationship_manager import assign_relationship_manager
from app.services.team_users import create_relationship_manager


OWNER = {"id": 1, "username": "mark", "role": "owner"}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def qualification_database(tmp_path, monkeypatch):
    path = tmp_path / "qualification.db"
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
        other_rm = create_relationship_manager(
            db,
            username="other-rm",
            display_name="Other RM",
            password="temporary-pass-456",
            password_confirmation="temporary-pass-456",
        )
        lead = create_lead(
            db,
            company="Discovery Co",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="Referral",
            source_url="https://example.com/discovery",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="new",
            priority="medium",
            next_action="Schedule discovery call.",
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
        "other_rm": dict(other_rm),
    }


def test_owning_relationship_manager_can_edit_qualification(
    qualification_database,
):
    organization_id = qualification_database["organization_id"]
    lead_id = qualification_database["lead_id"]
    junmar = qualification_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        updated = update_qualification_details(
            db,
            lead_id,
            actor=junmar_actor,
            organization_id=organization_id,
            business_problem="Manual weekly reporting wastes hours.",
            business_impact="Delays board decisions.",
            urgency="High — board meeting in three weeks.",
            budget_range="₱50,000-100,000/month",
            decision_maker="Dana Buyer, Founder",
        )

    assert updated["qualification_status"] == "in_progress"
    assert updated["business_problem"] == "Manual weekly reporting wastes hours."
    assert updated["qualification_updated_by_user_id"] == junmar["id"]


def test_unrelated_relationship_manager_cannot_edit(qualification_database):
    organization_id = qualification_database["organization_id"]
    lead_id = qualification_database["lead_id"]
    other_rm = qualification_database["other_rm"]
    other_actor = {"id": other_rm["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        with pytest.raises(LeadQualificationPermissionError):
            update_qualification_details(
                db,
                lead_id,
                actor=other_actor,
                organization_id=organization_id,
                business_problem="Should fail.",
            )


def test_owner_can_decide_qualification_and_rm_then_locked_out(
    qualification_database,
):
    organization_id = qualification_database["organization_id"]
    lead_id = qualification_database["lead_id"]
    junmar = qualification_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        update_qualification_details(
            db,
            lead_id,
            actor=junmar_actor,
            organization_id=organization_id,
            business_problem="Manual weekly reporting wastes hours.",
        )

        decided = decide_qualification(
            db,
            lead_id,
            actor=OWNER,
            decision="qualified",
            organization_id=organization_id,
        )

        assert decided["qualification_status"] == "qualified"
        assert decided["qualification_decided_by_user_id"] == OWNER["id"]

        with pytest.raises(LeadQualificationPermissionError):
            update_qualification_details(
                db,
                lead_id,
                actor=junmar_actor,
                organization_id=organization_id,
                business_problem="Trying to edit after decision.",
            )


def test_relationship_manager_cannot_decide_qualification(
    qualification_database,
):
    organization_id = qualification_database["organization_id"]
    lead_id = qualification_database["lead_id"]
    junmar = qualification_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        with pytest.raises(LeadQualificationPermissionError):
            decide_qualification(
                db,
                lead_id,
                actor=junmar_actor,
                decision="qualified",
                organization_id=organization_id,
            )


def test_invalid_decision_value_is_rejected(qualification_database):
    organization_id = qualification_database["organization_id"]
    lead_id = qualification_database["lead_id"]

    with database.get_db() as db:
        with pytest.raises(ValueError, match="qualified.*disqualified"):
            decide_qualification(
                db,
                lead_id,
                actor=OWNER,
                decision="maybe",
                organization_id=organization_id,
            )


def test_deciding_qualification_never_changes_pipeline_status(
    qualification_database,
):
    organization_id = qualification_database["organization_id"]
    lead_id = qualification_database["lead_id"]

    with database.get_db() as db:
        before = db.execute(
            "SELECT pipeline_status FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()["pipeline_status"]

        decide_qualification(
            db,
            lead_id,
            actor=OWNER,
            decision="qualified",
            organization_id=organization_id,
        )

        after = db.execute(
            "SELECT pipeline_status FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()["pipeline_status"]

    assert before == after == "new"


def test_stale_row_version_is_rejected(qualification_database):
    organization_id = qualification_database["organization_id"]
    lead_id = qualification_database["lead_id"]
    junmar = qualification_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        with pytest.raises(ValueError, match="changed after it was loaded"):
            update_qualification_details(
                db,
                lead_id,
                actor=junmar_actor,
                organization_id=organization_id,
                expected_row_version=999,
                business_problem="Stale attempt.",
            )


def test_can_edit_and_can_decide_helpers(qualification_database):
    organization_id = qualification_database["organization_id"]
    lead_id = qualification_database["lead_id"]
    junmar = qualification_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        lead = db.execute(
            "SELECT * FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()

    assert can_edit_qualification(junmar_actor, lead) is True
    assert can_edit_qualification(OWNER, lead) is True
    assert can_decide_qualification(junmar_actor, lead) is False
    assert can_decide_qualification(OWNER, lead) is True
