from __future__ import annotations

import pytest

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.webhook_intake import (
    WebhookAuthenticationError,
    WebhookIntakeError,
    authenticate_webhook_token,
    create_webhook_token,
    ingest_lead_payload,
    list_webhook_tokens,
    revoke_webhook_token,
)
from app.services.team_users import create_relationship_manager


OWNER = {"id": 1, "username": "mark", "role": "owner"}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def webhook_database(tmp_path, monkeypatch):
    path = tmp_path / "webhook-intake.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        mark_agency_id = organization_id_by_slug(db, "mark-agency")
        pendang_id = organization_id_by_slug(db, "pendang")
        rm = create_relationship_manager(
            db,
            username="junmar",
            display_name="Junmar",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )

    return {
        "path": path,
        "mark_agency_id": mark_agency_id,
        "pendang_id": pendang_id,
        "rm": dict(rm),
    }


def _valid_payload(external_id: str = "ext-1") -> dict:
    return {
        "external_id": external_id,
        "company": "Northstar Analytics",
        "contact_person": "Ada Reyes",
        "job_title": "Founder",
        "message": "Reporting is slow and difficult to trust.",
    }


def test_owner_can_issue_and_list_tokens(webhook_database):
    mark_agency_id = webhook_database["mark_agency_id"]
    with database.get_db() as db:
        issued = create_webhook_token(
            db,
            actor=OWNER,
            organization_id=mark_agency_id,
            source_name="Website contact form",
        )
        tokens = list_webhook_tokens(db, organization_id=mark_agency_id)

    assert len(issued.token) > 20
    assert len(tokens) == 1
    assert tokens[0]["source_name"] == "Website contact form"
    assert tokens[0]["active"] == 1
    assert tokens[0]["token_last_four"] == issued.token[-4:]
    assert "token_hash" not in tokens[0]


def test_relationship_manager_cannot_issue_tokens(webhook_database):
    mark_agency_id = webhook_database["mark_agency_id"]
    rm = webhook_database["rm"]
    with database.get_db() as db:
        with pytest.raises(PermissionError):
            create_webhook_token(
                db,
                actor=rm,
                organization_id=mark_agency_id,
                source_name="Should fail",
            )


def test_valid_token_authenticates_and_ingests_a_lead(webhook_database):
    mark_agency_id = webhook_database["mark_agency_id"]
    with database.get_db() as db:
        issued = create_webhook_token(
            db,
            actor=OWNER,
            organization_id=mark_agency_id,
            source_name="Website contact form",
        )
        token_record = authenticate_webhook_token(db, issued.token)
        result = ingest_lead_payload(
            db,
            token_record=token_record,
            payload=_valid_payload(),
        )

        lead = db.execute(
            "SELECT * FROM leads WHERE id = ?",
            (result.lead_id,),
        ).fetchone()

    assert result.created is True
    assert result.outcome == "created"
    assert lead["company"] == "Northstar Analytics"
    assert lead["source"] == "Website contact form"
    assert lead["research_status"] == "draft"
    assert lead["pipeline_status"] == "new"
    assert lead["organization_id"] == mark_agency_id


def test_invalid_token_is_rejected(webhook_database):
    with database.get_db() as db:
        with pytest.raises(WebhookAuthenticationError):
            authenticate_webhook_token(db, "not-a-real-token")


def test_revoked_token_is_rejected(webhook_database):
    mark_agency_id = webhook_database["mark_agency_id"]
    with database.get_db() as db:
        issued = create_webhook_token(
            db,
            actor=OWNER,
            organization_id=mark_agency_id,
            source_name="Revoked source",
        )
        revoke_webhook_token(
            db,
            issued.id,
            actor=OWNER,
            organization_id=mark_agency_id,
        )
        with pytest.raises(WebhookAuthenticationError):
            authenticate_webhook_token(db, issued.token)


def test_revoked_token_cannot_be_double_revoked(webhook_database):
    mark_agency_id = webhook_database["mark_agency_id"]
    with database.get_db() as db:
        issued = create_webhook_token(
            db,
            actor=OWNER,
            organization_id=mark_agency_id,
            source_name="Once source",
        )
        revoke_webhook_token(
            db,
            issued.id,
            actor=OWNER,
            organization_id=mark_agency_id,
        )
        with pytest.raises(ValueError):
            revoke_webhook_token(
                db,
                issued.id,
                actor=OWNER,
                organization_id=mark_agency_id,
            )


def test_missing_required_fields_are_rejected_and_not_written(
    webhook_database,
):
    mark_agency_id = webhook_database["mark_agency_id"]
    with database.get_db() as db:
        issued = create_webhook_token(
            db,
            actor=OWNER,
            organization_id=mark_agency_id,
            source_name="Strict source",
        )
        token_record = authenticate_webhook_token(db, issued.token)

        with pytest.raises(WebhookIntakeError):
            ingest_lead_payload(
                db,
                token_record=token_record,
                payload={"external_id": "missing-fields"},
            )

        lead_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        event = db.execute(
            "SELECT outcome, lead_id FROM webhook_intake_events "
            "WHERE external_id = 'missing-fields'"
        ).fetchone()

    assert lead_count == 0
    assert event["outcome"] == "rejected"
    assert event["lead_id"] is None


def test_duplicate_external_id_is_idempotent_not_duplicated(
    webhook_database,
):
    mark_agency_id = webhook_database["mark_agency_id"]
    with database.get_db() as db:
        issued = create_webhook_token(
            db,
            actor=OWNER,
            organization_id=mark_agency_id,
            source_name="Idempotency source",
        )
        token_record = authenticate_webhook_token(db, issued.token)

        first = ingest_lead_payload(
            db,
            token_record=token_record,
            payload=_valid_payload("same-id"),
        )
        second = ingest_lead_payload(
            db,
            token_record=token_record,
            payload=_valid_payload("same-id"),
        )

        lead_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    assert first.created is True
    assert second.created is False
    assert second.lead_id == first.lead_id
    assert lead_count == 1


def test_token_is_scoped_to_its_own_organization(webhook_database):
    mark_agency_id = webhook_database["mark_agency_id"]
    pendang_id = webhook_database["pendang_id"]
    with database.get_db() as db:
        issued = create_webhook_token(
            db,
            actor=OWNER,
            organization_id=mark_agency_id,
            source_name="Mark Agency source",
        )
        token_record = authenticate_webhook_token(db, issued.token)
        result = ingest_lead_payload(
            db,
            token_record=token_record,
            payload=_valid_payload(),
        )
        lead = db.execute(
            "SELECT organization_id FROM leads WHERE id = ?",
            (result.lead_id,),
        ).fetchone()

    assert int(lead["organization_id"]) == mark_agency_id
    assert int(lead["organization_id"]) != pendang_id
