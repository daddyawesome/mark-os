from __future__ import annotations

import pytest

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.client_delivery import (
    ClientDeliveryStateError,
    cancel_engagement,
    complete_engagement,
    create_engagement,
    create_engagement_item,
    get_client_by_lead,
    onboard_client_from_lead,
    update_engagement,
    update_engagement_item_status,
    update_engagement_notes,
)
from app.services.client_delivery_permissions import ClientDeliveryPermissionError
from app.services.lead_pipeline_workflow import change_pipeline_stage
from app.services.leads import create_lead
from app.services.relationship_manager import assign_relationship_manager
from app.services.team_users import create_lead_sourcer, create_relationship_manager


OWNER = {"id": 1, "username": "mark", "role": "owner"}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def delivery_database(tmp_path, monkeypatch):
    path = tmp_path / "client-delivery.db"
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
        sourcer = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        lead = create_lead(
            db,
            company="Delivery Co",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="Referral",
            source_url="https://example.com/delivery",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="meeting",
            priority="medium",
            next_action="Close the deal.",
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
        change_pipeline_stage(
            db,
            lead["id"],
            actor=OWNER,
            pipeline_status="proposal",
            organization_id=organization_id,
        )
        change_pipeline_stage(
            db,
            lead["id"],
            actor=OWNER,
            pipeline_status="won",
            organization_id=organization_id,
        )

    return {
        "organization_id": organization_id,
        "lead_id": lead["id"],
        "junmar": dict(junmar),
        "sourcer": dict(sourcer),
    }


def _onboard(db, organization_id, lead_id, **overrides):
    fields = {
        "actor": OWNER,
        "organization_id": organization_id,
        "engagement_title": "Initial delivery engagement",
    }
    fields.update(overrides)
    return onboard_client_from_lead(db, lead_id, **fields)


def test_owner_can_onboard_a_won_lead_as_a_client(delivery_database):
    organization_id = delivery_database["organization_id"]
    lead_id = delivery_database["lead_id"]
    junmar = delivery_database["junmar"]

    with database.get_db() as db:
        client = _onboard(db, organization_id, lead_id)
        engagements = db.execute(
            "SELECT * FROM client_engagements WHERE client_id = ?",
            (client["id"],),
        ).fetchall()

    assert client["company"] == "Delivery Co"
    assert client["lead_id"] == lead_id
    assert len(engagements) == 1
    assert engagements[0]["title"] == "Initial delivery engagement"
    assert engagements[0]["delivery_owner_user_id"] == junmar["id"]
    assert engagements[0]["status"] == "active"


def test_onboarding_twice_is_idempotent_not_duplicated(delivery_database):
    organization_id = delivery_database["organization_id"]
    lead_id = delivery_database["lead_id"]

    with database.get_db() as db:
        first = _onboard(db, organization_id, lead_id)
        second = _onboard(db, organization_id, lead_id)

        client_count = db.execute(
            "SELECT COUNT(*) FROM organization_clients WHERE lead_id = ?",
            (lead_id,),
        ).fetchone()[0]

    assert first["id"] == second["id"]
    assert client_count == 1


def test_cannot_onboard_a_lead_that_is_not_won(delivery_database, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", database.DB_PATH)
    organization_id = delivery_database["organization_id"]

    with database.get_db() as db:
        not_won_lead = create_lead(
            db,
            company="Not Won Co",
            contact_person="Dana Buyer",
            job_title="Founder",
            source="Referral",
            source_url="https://example.com/not-won",
            problem_opportunity="Reporting is manual.",
            why_mark_fits="Mark can automate reporting.",
            pipeline_status="new",
            priority="medium",
            next_action="Research.",
            notes="",
            organization_id=organization_id,
        ).lead

        with pytest.raises(ClientDeliveryStateError):
            _onboard(db, organization_id, not_won_lead["id"])


def test_relationship_manager_cannot_onboard_clients(delivery_database):
    organization_id = delivery_database["organization_id"]
    lead_id = delivery_database["lead_id"]
    junmar = delivery_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        with pytest.raises(ClientDeliveryPermissionError):
            _onboard(db, organization_id, lead_id, actor=junmar_actor)


def test_delivery_owner_can_update_notes_but_not_scope(delivery_database):
    organization_id = delivery_database["organization_id"]
    lead_id = delivery_database["lead_id"]
    junmar = delivery_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        client = _onboard(db, organization_id, lead_id)
        engagement = db.execute(
            "SELECT * FROM client_engagements WHERE client_id = ?",
            (client["id"],),
        ).fetchone()

        updated = update_engagement_notes(
            db,
            engagement["id"],
            actor=junmar_actor,
            organization_id=organization_id,
            notes="Kickoff call scheduled.",
        )
        assert updated["notes"] == "Kickoff call scheduled."

        with pytest.raises(ClientDeliveryPermissionError):
            update_engagement(
                db,
                engagement["id"],
                actor=junmar_actor,
                organization_id=organization_id,
                title="Renamed by RM",
            )


def test_unrelated_staff_cannot_touch_the_engagement(delivery_database):
    organization_id = delivery_database["organization_id"]
    lead_id = delivery_database["lead_id"]
    sourcer = delivery_database["sourcer"]
    sourcer_actor = {"id": sourcer["id"], "role": "lead_sourcer"}

    with database.get_db() as db:
        client = _onboard(db, organization_id, lead_id)
        engagement = db.execute(
            "SELECT * FROM client_engagements WHERE client_id = ?",
            (client["id"],),
        ).fetchone()

        with pytest.raises(ClientDeliveryPermissionError):
            update_engagement_notes(
                db,
                engagement["id"],
                actor=sourcer_actor,
                organization_id=organization_id,
                notes="Should fail.",
            )


def test_delivery_owner_can_complete_but_not_cancel(delivery_database):
    organization_id = delivery_database["organization_id"]
    lead_id = delivery_database["lead_id"]
    junmar = delivery_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        client = _onboard(db, organization_id, lead_id)
        engagement = db.execute(
            "SELECT * FROM client_engagements WHERE client_id = ?",
            (client["id"],),
        ).fetchone()

        with pytest.raises(ClientDeliveryPermissionError):
            cancel_engagement(
                db,
                engagement["id"],
                actor=junmar_actor,
                organization_id=organization_id,
            )

        completed = complete_engagement(
            db,
            engagement["id"],
            actor=junmar_actor,
            organization_id=organization_id,
        )
        assert completed["status"] == "completed"
        assert completed["completed_at"] is not None


def test_cannot_edit_scope_after_completion(delivery_database):
    organization_id = delivery_database["organization_id"]
    lead_id = delivery_database["lead_id"]

    with database.get_db() as db:
        client = _onboard(db, organization_id, lead_id)
        engagement = db.execute(
            "SELECT * FROM client_engagements WHERE client_id = ?",
            (client["id"],),
        ).fetchone()
        complete_engagement(
            db, engagement["id"], actor=OWNER, organization_id=organization_id
        )

        with pytest.raises(ClientDeliveryStateError):
            update_engagement(
                db,
                engagement["id"],
                actor=OWNER,
                organization_id=organization_id,
                title="Changed after completion",
            )


def test_milestones_and_tasks_lifecycle(delivery_database):
    organization_id = delivery_database["organization_id"]
    lead_id = delivery_database["lead_id"]
    junmar = delivery_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        client = _onboard(db, organization_id, lead_id)
        engagement = db.execute(
            "SELECT * FROM client_engagements WHERE client_id = ?",
            (client["id"],),
        ).fetchone()

        milestone = create_engagement_item(
            db,
            engagement["id"],
            actor=junmar_actor,
            organization_id=organization_id,
            item_type="milestone",
            title="Discovery complete",
            due_date="2026-09-01",
        )
        task = create_engagement_item(
            db,
            engagement["id"],
            actor=junmar_actor,
            organization_id=organization_id,
            item_type="task",
            title="Set up dashboard",
            assigned_to_user_id=junmar["id"],
        )

        assert milestone["item_type"] == "milestone"
        assert task["item_type"] == "task"
        assert task["assigned_to_user_id"] == junmar["id"]

        completed_task = update_engagement_item_status(
            db,
            task["id"],
            actor=junmar_actor,
            organization_id=organization_id,
            status="completed",
        )
        assert completed_task["status"] == "completed"
        assert completed_task["completed_by_user_id"] == junmar["id"]
        assert completed_task["completed_at"] is not None


def test_second_engagement_requires_owner_authority(delivery_database):
    organization_id = delivery_database["organization_id"]
    lead_id = delivery_database["lead_id"]
    junmar = delivery_database["junmar"]
    junmar_actor = {"id": junmar["id"], "role": "relationship_manager"}

    with database.get_db() as db:
        client = _onboard(db, organization_id, lead_id)

        with pytest.raises(ClientDeliveryPermissionError):
            create_engagement(
                db,
                client["id"],
                actor=junmar_actor,
                organization_id=organization_id,
                title="Renewal engagement",
            )

        renewal = create_engagement(
            db,
            client["id"],
            actor=OWNER,
            organization_id=organization_id,
            title="Renewal engagement",
        )
        assert renewal["client_id"] == client["id"]


def test_stale_row_version_is_rejected(delivery_database):
    organization_id = delivery_database["organization_id"]
    lead_id = delivery_database["lead_id"]

    with database.get_db() as db:
        client = _onboard(db, organization_id, lead_id)
        engagement = db.execute(
            "SELECT * FROM client_engagements WHERE client_id = ?",
            (client["id"],),
        ).fetchone()

        with pytest.raises(ValueError, match="changed in another session"):
            update_engagement(
                db,
                engagement["id"],
                actor=OWNER,
                organization_id=organization_id,
                expected_row_version=999,
                title="Stale attempt",
            )
