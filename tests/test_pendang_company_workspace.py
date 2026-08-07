from __future__ import annotations

import pytest

from app import database
from app.services.access_control import can_access_request, landing_path_for_user
from app.services.pendang_company import (
    PendangCompanyConflictError,
    PendangCompanyPermissionError,
    archive_knowledge_item,
    create_knowledge_item,
    load_company_home,
    update_company_profile,
    update_knowledge_item,
)
from app.services.team_users import create_lead_sourcer


EXPECTED_SERVICE_TITLES = {
    "Research & Statistics",
    "Data Analysis & BI",
    "Data Engineering & Automation",
    "Practical AI",
}


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _actor(db, user_id: int, workspace_slug: str) -> dict:
    user = db.execute(
        "SELECT id, username, display_name, role FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    membership = db.execute(
        """
        SELECT o.id, o.slug, o.name, m.membership_role
        FROM organization_memberships AS m
        JOIN organizations AS o ON o.id = m.organization_id
        WHERE m.user_id = ?
          AND o.slug = ?
          AND m.active = 1
        """,
        (user_id, workspace_slug),
    ).fetchone()
    assert user is not None
    assert membership is not None
    result = dict(user)
    result["current_workspace"] = dict(membership)
    result["workspace_membership_role"] = membership["membership_role"]
    return result


def test_pendang_company_schema_and_seed_are_idempotent(tmp_path, monkeypatch):
    database_path = tmp_path / "pendang-company-seed.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()
    database.init_db()

    with database.get_db() as db:
        pendang_id = int(
            db.execute(
                "SELECT id FROM organizations WHERE slug = 'pendang'"
            ).fetchone()["id"]
        )
        profile = db.execute(
            """
            SELECT founder_plan, row_version
            FROM organization_company_profiles
            WHERE organization_id = ?
            """,
            (pendang_id,),
        ).fetchone()
        services = db.execute(
            """
            SELECT title
            FROM organization_knowledge_items
            WHERE organization_id = ?
              AND item_type = 'service'
              AND deleted_at IS NULL
            """,
            (pendang_id,),
        ).fetchall()
        indexes = {
            row["name"]
            for row in db.execute(
                "PRAGMA index_list(organization_knowledge_items)"
            ).fetchall()
        }
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()

    assert profile is not None
    assert "Leads → Clients → Projects → Payment → Referrals" in profile["founder_plan"]
    assert profile["row_version"] == 1
    assert {row["title"] for row in services} == EXPECTED_SERVICE_TITLES
    assert "uq_organization_knowledge_active_title" in indexes
    assert foreign_keys == []


def test_owner_can_manage_profile_and_items_with_optimistic_conflicts(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "pendang-company-owner.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = int(
            db.execute("SELECT id FROM users WHERE username = 'mark'").fetchone()["id"]
        )
        owner = _actor(db, owner_id, "pendang")
        home = load_company_home(db, owner)
        assert home["can_manage"] is True

        updated = update_company_profile(
            db,
            owner,
            founder_plan=home["profile"]["founder_plan"],
            about_company="Pendang provides research, statistics, and data services.",
            company_cv="Verified capabilities will be recorded here.",
            expected_row_version=home["profile"]["row_version"],
        )
        assert updated["row_version"] == 2

        with pytest.raises(PendangCompanyConflictError):
            update_company_profile(
                db,
                owner,
                founder_plan=home["profile"]["founder_plan"],
                about_company="Stale overwrite",
                company_cv="",
                expected_row_version=1,
            )

        item = create_knowledge_item(
            db,
            owner,
            item_type="project",
            title="Verified Analytics Project",
            body="A historical project can be documented here after verification.",
            status="draft",
        )
        assert item["row_version"] == 1

        changed = update_knowledge_item(
            db,
            owner,
            item["id"],
            title=item["title"],
            body="Updated verified project context.",
            status="active",
            expected_row_version=item["row_version"],
        )
        assert changed["row_version"] == 2

        with pytest.raises(PendangCompanyConflictError):
            update_knowledge_item(
                db,
                owner,
                item["id"],
                title=item["title"],
                status="active",
                expected_row_version=1,
            )

        archive_knowledge_item(
            db,
            owner,
            item["id"],
            expected_row_version=changed["row_version"],
        )
        refreshed = load_company_home(db, owner)
        assert refreshed["items_by_type"]["project"] == []


def test_pendang_crm_contributor_can_read_but_cannot_manage(tmp_path, monkeypatch):
    database_path = tmp_path / "pendang-company-readonly.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        staff = create_lead_sourcer(
            db,
            username="pendang-researcher",
            display_name="Pendang Researcher",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
            workspace_slug="pendang",
        )
        actor = _actor(db, int(staff["id"]), "pendang")
        home = load_company_home(db, actor)
        assert home["can_manage"] is False
        assert home["items_by_type"]["service"]

        with pytest.raises(PendangCompanyPermissionError):
            create_knowledge_item(
                db,
                actor,
                item_type="relationship",
                title="Should not write",
            )


def test_mark_agency_only_staff_cannot_read_pendang_company_data(tmp_path, monkeypatch):
    database_path = tmp_path / "pendang-company-foreign.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        staff = create_lead_sourcer(
            db,
            username="mark-agency-researcher",
            display_name="MARK Agency Researcher",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
            workspace_slug="mark-agency",
        )
        actor = _actor(db, int(staff["id"]), "mark-agency")
        with pytest.raises(PendangCompanyPermissionError):
            load_company_home(db, actor)


def test_company_item_validation_rejects_unsafe_or_duplicate_entries(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "pendang-company-validation.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = int(
            db.execute("SELECT id FROM users WHERE username = 'mark'").fetchone()["id"]
        )
        owner = _actor(db, owner_id, "pendang")

        with pytest.raises(ValueError, match="http"):
            create_knowledge_item(
                db,
                owner,
                item_type="document",
                title="Unsafe link",
                reference_url="javascript:alert(1)",
            )

        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            create_knowledge_item(
                db,
                owner,
                item_type="meeting_preparation",
                title="Invalid date",
                scheduled_for="08/14/2026",
            )

        with pytest.raises(ValueError, match="already exists"):
            create_knowledge_item(
                db,
                owner,
                item_type="service",
                title="Research & Statistics",
            )


def test_pendang_landing_and_request_access_follow_active_workspace():
    rey = {
        "role": "relationship_manager",
        "current_workspace": {
            "slug": "pendang",
            "membership_role": "workspace_owner",
        },
    }
    freddy = {
        "role": "lead_sourcer",
        "current_workspace": {
            "slug": "pendang",
            "membership_role": "crm_contributor",
        },
    }
    mark_agency_researcher = {
        "role": "lead_sourcer",
        "current_workspace": {
            "slug": "mark-agency",
            "membership_role": "crm_contributor",
        },
    }

    assert landing_path_for_user(rey) == "/pendang"
    assert landing_path_for_user(freddy) == "/pendang"
    assert landing_path_for_user(mark_agency_researcher) == "/crm"
    assert can_access_request(rey, "GET", "/pendang") is True
    assert can_access_request(rey, "POST", "/pendang/items") is True
    assert can_access_request(freddy, "GET", "/pendang") is True
    assert can_access_request(freddy, "POST", "/pendang/items") is False
    assert can_access_request(mark_agency_researcher, "GET", "/pendang") is False
