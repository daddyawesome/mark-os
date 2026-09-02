from __future__ import annotations

import pytest

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.outreach_templates import (
    OutreachTemplatePermissionError,
    archive_template,
    create_template,
    extract_template_variables,
    get_template,
    list_templates,
    render_template,
    set_template_approval,
    update_template,
)
from app.services.team_users import create_relationship_manager


OWNER = {"id": 1, "username": "mark", "role": "owner"}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def templates_database(tmp_path, monkeypatch):
    path = tmp_path / "outreach-templates.db"
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


def test_seeded_templates_exist_unapproved_per_workspace(templates_database):
    mark_agency_id = templates_database["mark_agency_id"]
    pendang_id = templates_database["pendang_id"]

    with database.get_db() as db:
        mark_templates = list_templates(db, organization_id=mark_agency_id)
        pendang_templates = list_templates(db, organization_id=pendang_id)

    assert len(mark_templates) == 6
    assert len(pendang_templates) == 6
    assert all(not template["approved"] for template in mark_templates)
    assert all(not template["approved"] for template in pendang_templates)


def test_owner_can_create_update_approve_and_archive(templates_database):
    mark_agency_id = templates_database["mark_agency_id"]

    with database.get_db() as db:
        created = create_template(
            db,
            actor=OWNER,
            organization_id=mark_agency_id,
            title="Custom Warm Note",
            category="warm_introduction",
            body="Hi {{contact_person}}, {{opening_note}}.",
        )
        assert created["approved"] == 0
        assert set(created["variables"]) == {"contact_person", "opening_note"}

        updated = update_template(
            db,
            created["id"],
            actor=OWNER,
            organization_id=mark_agency_id,
            title="Custom Warm Note",
            category="warm_introduction",
            body="Hi {{contact_person}}, updated note.",
            expected_row_version=created["row_version"],
        )
        assert updated["row_version"] == created["row_version"] + 1
        assert "updated note" in updated["body"]

        approved = set_template_approval(
            db,
            created["id"],
            actor=OWNER,
            organization_id=mark_agency_id,
            approved=True,
            expected_row_version=updated["row_version"],
        )
        assert approved["approved"] == 1
        assert approved["approved_by_user_id"] == OWNER["id"]

        archive_template(
            db,
            created["id"],
            actor=OWNER,
            organization_id=mark_agency_id,
            expected_row_version=approved["row_version"],
        )
        assert get_template(
            db,
            created["id"],
            organization_id=mark_agency_id,
        ) is None


def test_relationship_manager_cannot_manage_templates(templates_database):
    mark_agency_id = templates_database["mark_agency_id"]
    rm = templates_database["rm"]

    with database.get_db() as db:
        with pytest.raises(OutreachTemplatePermissionError):
            create_template(
                db,
                actor=rm,
                organization_id=mark_agency_id,
                title="Should Fail",
                category="warm_introduction",
                body="Hi {{contact_person}}.",
            )


def test_relationship_manager_sees_only_approved_templates(
    templates_database,
):
    mark_agency_id = templates_database["mark_agency_id"]

    with database.get_db() as db:
        all_templates = list_templates(db, organization_id=mark_agency_id)
        one = all_templates[0]
        set_template_approval(
            db,
            one["id"],
            actor=OWNER,
            organization_id=mark_agency_id,
            approved=True,
            expected_row_version=one["row_version"],
        )

        approved_only = list_templates(
            db,
            organization_id=mark_agency_id,
            approved_only=True,
        )

    assert len(approved_only) == 1
    assert approved_only[0]["id"] == one["id"]


def test_templates_are_workspace_isolated(templates_database):
    mark_agency_id = templates_database["mark_agency_id"]
    pendang_id = templates_database["pendang_id"]

    with database.get_db() as db:
        created = create_template(
            db,
            actor=OWNER,
            organization_id=mark_agency_id,
            title="Mark Agency Only",
            category="warm_introduction",
            body="Hi {{contact_person}}.",
        )

        pendang_templates = list_templates(db, organization_id=pendang_id)

    assert all(
        template["id"] != created["id"] for template in pendang_templates
    )


def test_row_version_conflict_is_rejected(templates_database):
    mark_agency_id = templates_database["mark_agency_id"]

    with database.get_db() as db:
        created = create_template(
            db,
            actor=OWNER,
            organization_id=mark_agency_id,
            title="Conflict Check",
            category="follow_up",
            body="Hi {{contact_person}}.",
        )

        with pytest.raises(ValueError, match="changed in another session"):
            update_template(
                db,
                created["id"],
                actor=OWNER,
                organization_id=mark_agency_id,
                title="Conflict Check",
                category="follow_up",
                body="Different body.",
                expected_row_version=created["row_version"] + 1,
            )


def test_render_template_substitutes_known_and_preserves_unknown():
    body = "Hi {{contact_person}}, from {{sender_name}}. {{missing}}"
    rendered = render_template(
        body,
        {"contact_person": "Dana", "sender_name": "Junmar"},
    )
    assert rendered == "Hi Dana, from Junmar. {{missing}}"


def test_extract_template_variables_is_sorted_and_deduplicated():
    body = "{{b}} then {{a}} then {{b}} again"
    assert extract_template_variables(body) == ("a", "b")
