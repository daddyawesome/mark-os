from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import Request

from app import database
from app.db import leads as lead_db
from app.routes import client_hunting
from app.services.lead_pipeline_workflow import approve_outreach
from app.services.lead_research_workflow import (
    review_research,
    submit_research_for_review,
    update_research_details,
)
from app.services.leads import (
    LeadEditConflictError,
    create_lead,
    delete_lead,
    get_lead,
    update_lead,
    update_lead_next_action,
    update_lead_pipeline,
)
from app.services.relationship_manager import assign_relationship_manager
from app.services.team_users import (
    create_lead_sourcer,
    create_relationship_manager,
    get_primary_owner_id,
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def optimistic_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "optimistic.db")
    _configure_owner(monkeypatch)
    database.init_db()
    return tmp_path / "optimistic.db"


def _owner(db) -> dict:
    owner_id = get_primary_owner_id(db)
    assert owner_id is not None
    return dict(
        db.execute(
            """
            SELECT id, username, display_name, role, active
            FROM users
            WHERE id = ?
            """,
            (owner_id,),
        ).fetchone()
    )


def _workspace(db, slug: str = "mark-agency") -> dict:
    row = db.execute(
        "SELECT id, slug, name FROM organizations WHERE slug = ?",
        (slug,),
    ).fetchone()
    assert row is not None
    return {
        "id": int(row["id"]),
        "slug": row["slug"],
        "name": row["name"],
        "membership_role": "workspace_admin",
    }


def _request(user: dict, workspace: dict, path: str) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "raw_path": path.encode(),
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "state": {
                "current_user": user,
                "current_workspace": workspace,
                "authorized_workspaces": [workspace],
            },
        }
    )
    return request


def _create(db, *, suffix: str = "one", **overrides):
    owner = _owner(db)
    workspace = _workspace(db)
    payload = {
        "company": f"Versioned {suffix}",
        "contact_person": f"Buyer {suffix}",
        "source": "LinkedIn",
        "problem_opportunity": "Needs a reliable CRM workflow.",
        "why_mark_fits": "The team can deliver the workflow.",
        "next_action": "Review the opportunity.",
        "request_key": f"optimistic-{suffix}",
        "created_by_user_id": owner["id"],
        "assigned_to_user_id": owner["id"],
        "organization_id": workspace["id"],
    }
    payload.update(overrides)
    return create_lead(db, **payload).lead


def test_row_version_migration_is_additive_idempotent_and_preserves_rows(
    optimistic_db,
):
    with database.get_db() as db:
        lead = _create(db, suffix="migration")
        before = dict(lead)
        db.execute("ALTER TABLE leads DROP COLUMN row_version")
        assert "row_version" not in {
            row["name"] for row in db.execute("PRAGMA table_info(leads)")
        }

        lead_db.migrate_row_version(db)
        lead_db.migrate_row_version(db)
        lead_db.validate_schema(
            db,
            require_organization=True,
            require_row_version=True,
        )

        after = dict(
            db.execute(
                "SELECT * FROM leads WHERE id = ?",
                (before["id"],),
            ).fetchone()
        )
        assert after["row_version"] == 1
        for field in (
            "id",
            "organization_id",
            "quest_id",
            "created_by_user_id",
            "assigned_to_user_id",
            "company",
            "contact_person",
            "request_key",
            "dedupe_key",
            "created_at",
            "updated_at",
            "deleted_at",
        ):
            assert after[field] == before[field]

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE leads SET row_version = 0 WHERE id = ?",
                (before["id"],),
            )


def test_core_edit_rejects_stale_snapshot_without_overwrite(optimistic_db):
    with database.get_db() as db:
        lead = _create(db, suffix="core")
        stale_version = int(lead["row_version"])

        first = update_lead_next_action(
            db,
            int(lead["id"]),
            next_action="Fresh next action",
            organization_id=int(lead["organization_id"]),
            expected_row_version=stale_version,
        )
        assert first["row_version"] == stale_version + 1

        with pytest.raises(LeadEditConflictError, match="changed"):
            update_lead(
                db,
                int(lead["id"]),
                notes="stale overwrite",
                organization_id=int(lead["organization_id"]),
                expected_row_version=stale_version,
            )

        latest = get_lead(
            db,
            int(lead["id"]),
            organization_id=int(lead["organization_id"]),
        )
        assert latest["next_action"] == "Fresh next action"
        assert latest["notes"] == ""
        assert latest["row_version"] == stale_version + 1


def test_pipeline_and_archive_require_the_expected_workspace_version(optimistic_db):
    with database.get_db() as db:
        lead = _create(db, suffix="pipeline")
        original_version = int(lead["row_version"])
        moved = update_lead_pipeline(
            db,
            int(lead["id"]),
            pipeline_status="reviewed",
            organization_id=int(lead["organization_id"]),
            expected_row_version=original_version,
        )
        assert moved["row_version"] == original_version + 1

        with pytest.raises(LeadEditConflictError):
            delete_lead(
                db,
                int(lead["id"]),
                confirmed=True,
                actor=_owner(db),
                organization_id=int(lead["organization_id"]),
                expected_row_version=original_version,
            )

        latest = get_lead(
            db,
            int(lead["id"]),
            organization_id=int(lead["organization_id"]),
        )
        assert latest is not None
        assert latest["deleted_at"] is None
        assert latest["pipeline_status"] == "reviewed"


def test_research_review_and_outreach_each_advance_version(optimistic_db):
    with database.get_db() as db:
        owner = _owner(db)
        sourcer = dict(
            create_lead_sourcer(
                db,
                username="researcher-version",
                display_name="Researcher Version",
                password="temporary-pass-123",
                password_confirmation="temporary-pass-123",
            )
        )
        lead = _create(
            db,
            suffix="research",
            created_by_user_id=sourcer["id"],
            assigned_to_user_id=sourcer["id"],
        )

        edited = update_research_details(
            db,
            int(lead["id"]),
            actor=sourcer,
            company=lead["company"],
            contact_person=lead["contact_person"],
            source=lead["source"],
            problem_opportunity=lead["problem_opportunity"],
            why_mark_fits=lead["why_mark_fits"],
            next_action="Research complete.",
            organization_id=int(lead["organization_id"]),
            expected_row_version=int(lead["row_version"]),
        )
        assert edited["row_version"] > lead["row_version"]

        submitted = submit_research_for_review(
            db,
            int(lead["id"]),
            actor=sourcer,
            organization_id=int(lead["organization_id"]),
            expected_row_version=int(edited["row_version"]),
        )
        assert submitted["row_version"] == edited["row_version"] + 1

        reviewed = review_research(
            db,
            int(lead["id"]),
            actor=owner,
            decision="approved",
            organization_id=int(lead["organization_id"]),
            expected_row_version=int(submitted["row_version"]),
        )
        assert reviewed["row_version"] == submitted["row_version"] + 1

        approved = approve_outreach(
            db,
            int(lead["id"]),
            actor=owner,
            organization_id=int(lead["organization_id"]),
            expected_row_version=int(reviewed["row_version"]),
        )
        assert approved["row_version"] == reviewed["row_version"] + 1

        with pytest.raises(LeadEditConflictError):
            review_research(
                db,
                int(lead["id"]),
                actor=owner,
                decision="approved",
                organization_id=int(lead["organization_id"]),
                expected_row_version=int(submitted["row_version"]),
            )


def test_relationship_assignment_is_conflict_safe(optimistic_db):
    with database.get_db() as db:
        owner = _owner(db)
        manager = dict(
            create_relationship_manager(
                db,
                username="manager-version",
                display_name="Manager Version",
                password="temporary-pass-456",
                password_confirmation="temporary-pass-456",
            )
        )
        lead = _create(db, suffix="relationship")
        version = int(lead["row_version"])

        assigned = assign_relationship_manager(
            db,
            int(lead["id"]),
            actor=owner,
            relationship_manager_user_id=int(manager["id"]),
            organization_id=int(lead["organization_id"]),
            expected_row_version=version,
        )
        assert assigned["row_version"] == version + 1

        with pytest.raises(LeadEditConflictError):
            assign_relationship_manager(
                db,
                int(lead["id"]),
                actor=owner,
                relationship_manager_user_id=None,
                organization_id=int(lead["organization_id"]),
                expected_row_version=version,
            )


def test_runtime_next_action_route_redirects_stale_form_without_overwrite(
    optimistic_db,
):
    with database.get_db() as db:
        owner = _owner(db)
        workspace = _workspace(db)
        lead = _create(db, suffix="route")
        stale_version = int(lead["row_version"])
        update_lead_next_action(
            db,
            int(lead["id"]),
            next_action="Newer server value",
            organization_id=workspace["id"],
            expected_row_version=stale_version,
        )

    request = _request(
        owner,
        workspace,
        f"/crm/leads/{lead['id']}/next-action",
    )
    response = client_hunting.update_next_action(
        request,
        int(lead["id"]),
        next_action="Stale browser value",
        next_action_due_date="",
        row_version=str(stale_version),
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("?error=stale")

    with database.get_db() as db:
        latest = get_lead(
            db,
            int(lead["id"]),
            organization_id=workspace["id"],
        )
        assert latest["next_action"] == "Newer server value"


def test_mutating_lead_forms_carry_row_version_and_stale_copy_is_user_visible():
    root = Path(__file__).resolve().parents[1]
    templates = {
        "detail": (root / "app/templates/lead_detail.html").read_text(),
        "edit": (root / "app/templates/partials/lead_form_fields.html").read_text(),
        "research": (root / "app/templates/edit_lead_research.html").read_text(),
        "delete": (root / "app/templates/delete_lead.html").read_text(),
        "review": (
            root / "app/templates/partials/lead_research_review_panel.html"
        ).read_text(),
        "outreach": (
            root / "app/templates/partials/lead_outreach_approval_panel.html"
        ).read_text(),
        "contacted": (
            root / "app/templates/partials/lead_contacted_transition.html"
        ).read_text(),
    }
    hidden = 'name="row_version" value="{{ lead.row_version }}"'
    assert templates["detail"].count(hidden) >= 4
    for key in ("edit", "research", "delete", "review", "outreach", "contacted"):
        assert hidden in templates[key], key

    routes = (root / "app/routes/client_hunting.py").read_text()
    assert '"stale": "This lead changed in another session.' in routes
    with pytest.raises(ValueError, match="row version is required"):
        client_hunting._expected_row_version("")
