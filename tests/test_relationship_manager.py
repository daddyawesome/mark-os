from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.responses import PlainTextResponse

from app import database
import app.main as main_module
from app.routes import client_hunting
from app.routes.relationship_manager import relationship_manager_home
from app.services.access_control import (
    can_access_request,
    landing_path_for_user,
    permitted_destination,
)
from app.services.lead_pipeline_workflow import change_pipeline_stage
from app.services.lead_research_permissions import LeadPermissionError, can_view_lead
from app.services.leads import create_lead, get_lead
from app.services.passwords import hash_password
from app.services.playbooks import (
    assign_playbook_to_user,
    get_primary_playbook_for_user,
    render_markdown_safely,
    upsert_playbook,
)
from app.services.relationship_manager import (
    assign_relationship_manager,
    load_relationship_manager_dashboard,
    update_next_action_for_actor,
)
from app.services.team_users import (
    create_lead_sourcer,
    create_relationship_manager,
    get_primary_owner_id,
    set_user_active,
)


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


@pytest.fixture
def relationship_database(tmp_path, monkeypatch):
    path = tmp_path / "relationship-manager.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db)
        owner = dict(
            db.execute(
                """
                SELECT id, username, display_name, role, active
                FROM users
                WHERE id = ?
                """,
                (owner_id,),
            ).fetchone()
        )
        junmar = create_relationship_manager(
            db,
            username="junmar",
            display_name="Junmar",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        other_manager = create_relationship_manager(
            db,
            username="other-manager",
            display_name="Other Manager",
            password="temporary-pass-456",
            password_confirmation="temporary-pass-456",
        )
        brother = create_lead_sourcer(
            db,
            username="brother",
            display_name="Brother",
            password="temporary-pass-789",
            password_confirmation="temporary-pass-789",
        )

    return {
        "path": path,
        "owner": owner,
        "junmar": dict(junmar),
        "other_manager": dict(other_manager),
        "brother": dict(brother),
    }


def _create(
    db,
    *,
    company: str,
    creator_id: int,
    owner_id: int,
    relationship_manager_id: int | None = None,
):
    return create_lead(
        db,
        company=company,
        contact_person=f"{company} Contact",
        job_title="Founder",
        source="LinkedIn",
        source_url=(
            "https://example.com/"
            + company.casefold().replace(" ", "-")
        ),
        problem_opportunity="Reporting is still manual.",
        why_mark_fits="Mark can automate the reporting process.",
        pipeline_status="new",
        priority="high",
        next_action="Qualify the reporting problem.",
        next_action_due_date="2026-08-01",
        notes="Relationship Manager test fixture.",
        request_key=(
            "relationship-manager-"
            + company.casefold().replace(" ", "-")
        ),
        created_by_user_id=creator_id,
        assigned_to_user_id=owner_id,
        business_development_owner_user_id=relationship_manager_id,
    ).lead


def _request(path: str = "/relationship-manager") -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    return request


def _game_state(db):
    return [
        tuple(row)
        for row in db.execute(
            """
            SELECT id, user_id, level, xp_total, xp_into_level,
                   last_level_up_at
            FROM game_state
            ORDER BY id
            """
        ).fetchall()
    ]


def test_fresh_schema_supports_relationship_manager_and_playbooks(
    relationship_database,
):
    path = relationship_database["path"]
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    table_sql = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'users'
        """
    ).fetchone()["sql"]
    lead_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(leads)").fetchall()
    }
    lead_indexes = {
        row["name"]
        for row in db.execute("PRAGMA index_list(leads)").fetchall()
    }
    tables = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    assert "'relationship_manager'" in table_sql
    assert "business_development_owner_user_id" in lead_columns
    assert "idx_leads_business_development_owner" in lead_indexes
    assert {"playbooks", "user_playbook_assignments"}.issubset(tables)

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO users (
                username, display_name, password_hash, role
            )
            VALUES ('bad-role', 'Bad Role', 'hash', 'sales_admin')
            """
        )

    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_previous_three_role_schema_rebuild_preserves_children(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "previous-three-role.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db)
        sourcer = create_lead_sourcer(
            db,
            username="legacy-sourcer",
            display_name="Legacy Sourcer",
            password="legacy-password-123",
            password_confirmation="legacy-password-123",
        )
        lead = _create(
            db,
            company="Legacy Relationship Data",
            creator_id=sourcer["id"],
            owner_id=owner_id,
        )
        playbook = upsert_playbook(
            db,
            slug="legacy-playbook",
            title="Legacy Playbook",
            markdown_content="# Legacy\nPreserve this content.",
            created_by_user_id=owner_id,
        )
        users_before = [
            tuple(row)
            for row in db.execute(
                """
                SELECT id, username, display_name, password_hash, role,
                       active, must_change_password, session_version,
                       last_login_at, created_at, updated_at
                FROM users
                ORDER BY id
                """
            ).fetchall()
        ]

        db.commit()
        db.execute("PRAGMA foreign_keys = OFF")
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                CREATE TABLE users_previous_roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE
                        CHECK(length(trim(username)) > 0),
                    display_name TEXT NOT NULL
                        CHECK(length(trim(display_name)) > 0),
                    password_hash TEXT NOT NULL
                        CHECK(length(trim(password_hash)) > 0),
                    role TEXT NOT NULL DEFAULT 'lead_sourcer'
                        CHECK(role IN (
                            'owner', 'member', 'lead_sourcer'
                        )),
                    active INTEGER NOT NULL DEFAULT 1
                        CHECK(active IN (0, 1)),
                    must_change_password INTEGER NOT NULL DEFAULT 0
                        CHECK(must_change_password IN (0, 1)),
                    session_version INTEGER NOT NULL DEFAULT 1
                        CHECK(session_version >= 1),
                    last_login_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            db.execute(
                """
                INSERT INTO users_previous_roles
                SELECT * FROM users
                """
            )
            db.execute("DROP TABLE users")
            db.execute(
                "ALTER TABLE users_previous_roles RENAME TO users"
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.execute("PRAGMA foreign_keys = ON")

    database.init_db()

    with database.get_db() as db:
        users_after = [
            tuple(row)
            for row in db.execute(
                """
                SELECT id, username, display_name, password_hash, role,
                       active, must_change_password, session_version,
                       last_login_at, created_at, updated_at
                FROM users
                ORDER BY id
                """
            ).fetchall()
        ]
        migrated_sql = db.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'users'
            """
        ).fetchone()["sql"]
        persisted_lead = get_lead(db, lead["id"])
        persisted_playbook = db.execute(
            "SELECT * FROM playbooks WHERE id = ?",
            (playbook["id"],),
        ).fetchone()

        assert users_after == users_before
        assert "'relationship_manager'" in migrated_sql
        assert persisted_lead["created_by_user_id"] == sourcer["id"]
        assert persisted_playbook["created_by_user_id"] == owner_id
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_relationship_manager_access_surface_is_narrow(
    relationship_database,
):
    junmar = relationship_database["junmar"]

    allowed = (
        ("GET", "/relationship-manager"),
        ("GET", "/crm"),
        ("GET", "/crm/leads/new"),
        ("GET", "/crm/leads/import/template"),
        ("GET", "/crm/leads/7"),
        ("POST", "/crm/leads"),
        ("POST", "/crm/leads/import"),
        ("POST", "/crm/leads/7/next-action"),
        ("POST", "/logout"),
    )
    denied = (
        ("GET", "/"),
        ("GET", "/quests"),
        ("GET", "/history"),
        ("GET", "/settings/users"),
        ("GET", "/crm/research-review"),
        ("GET", "/crm/leads/7/research/edit"),
        ("POST", "/crm/leads/7/research/submit"),
        ("POST", "/crm/leads/7/research/review"),
        ("POST", "/crm/leads/7/outreach/approve"),
        ("POST", "/crm/leads/7/pipeline"),
        ("POST", "/crm/leads/7/relationship-owner"),
        ("GET", "/crm/leads/7/delete"),
        ("POST", "/crm/leads/7/delete"),
    )

    assert all(
        can_access_request(junmar, method, path)
        for method, path in allowed
    )
    assert not any(
        can_access_request(junmar, method, path)
        for method, path in denied
    )
    assert landing_path_for_user(junmar) == "/relationship-manager"
    assert permitted_destination(junmar, "/") == "/relationship-manager"


def test_middleware_blocks_forged_owner_actions_and_private_pages(
    relationship_database,
    monkeypatch,
):
    junmar = relationship_database["junmar"]
    monkeypatch.setattr(
        main_module,
        "current_user",
        lambda request: junmar,
    )
    called = {"value": False}

    async def call_next(request):
        called["value"] = True
        return PlainTextResponse("must not execute")

    # The helper creates GET requests, so build the forged POST explicitly.
    forged_post = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/crm/leads/1/pipeline",
            "raw_path": b"/crm/leads/1/pipeline",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    post_response = asyncio.run(
        main_module.login_and_permission_guard(
            forged_post,
            call_next,
        )
    )
    private_get = asyncio.run(
        main_module.login_and_permission_guard(
            _request("/quests"),
            call_next,
        )
    )

    assert post_response.status_code == 403
    assert post_response.body == b"Forbidden"
    assert private_get.status_code == 303
    assert (
        private_get.headers["location"]
        == "/relationship-manager?error=forbidden"
    )
    assert called["value"] is False


def test_relationship_manager_created_lead_is_new_and_relationship_owned(
    relationship_database,
):
    owner = relationship_database["owner"]
    junmar = relationship_database["junmar"]
    request = SimpleNamespace(
        state=SimpleNamespace(current_user=junmar)
    )

    response = client_hunting.create_lead(
        request,
        company="Junmar Qualified Lead",
        contact_person="Qualified Buyer",
        source="Warm introduction",
        problem_opportunity="Manual monthly reporting.",
        why_mark_fits="Mark can automate the reports.",
        next_action="Confirm discovery-call interest.",
        job_title="Operations Director",
        source_url="https://example.com/junmar-qualified",
        pipeline_status="won",
        priority="high",
        next_action_due_date="2026-08-15",
        notes="Created by Junmar.",
        request_key="junmar-qualified-route",
    )

    assert response.status_code == 303
    with database.get_db() as db:
        lead = db.execute(
            """
            SELECT *
            FROM leads
            WHERE company = 'Junmar Qualified Lead'
            """
        ).fetchone()

        assert lead["pipeline_status"] == "new"
        assert lead["created_by_user_id"] == junmar["id"]
        assert (
            lead["business_development_owner_user_id"]
            == junmar["id"]
        )
        assert lead["assigned_to_user_id"] == owner["id"]


def test_relationship_visibility_and_next_action_are_service_enforced(
    relationship_database,
):
    owner = relationship_database["owner"]
    junmar = relationship_database["junmar"]
    other = relationship_database["other_manager"]

    with database.get_db() as db:
        lead = _create(
            db,
            company="Junmar Relationship",
            creator_id=owner["id"],
            owner_id=owner["id"],
            relationship_manager_id=junmar["id"],
        )

        assert can_view_lead(junmar, lead)
        assert not can_view_lead(other, lead)

        updated = update_next_action_for_actor(
            db,
            lead["id"],
            actor=junmar,
            next_action="Ask the qualification questions.",
            next_action_due_date="2026-08-18",
        )
        assert (
            updated["next_action"]
            == "Ask the qualification questions."
        )

        with pytest.raises(LeadPermissionError):
            update_next_action_for_actor(
                db,
                lead["id"],
                actor=other,
                next_action="Forged update.",
            )

        with pytest.raises(LeadPermissionError):
            change_pipeline_stage(
                db,
                lead["id"],
                actor=junmar,
                pipeline_status="contacted",
            )

        unchanged = get_lead(db, lead["id"])
        assert unchanged["pipeline_status"] == "new"


def test_owner_assignment_and_deactivation_preserve_xp_and_clear_owner(
    relationship_database,
):
    owner = relationship_database["owner"]
    junmar = relationship_database["junmar"]

    with database.get_db() as db:
        lead = _create(
            db,
            company="Owner Assigned Relationship",
            creator_id=owner["id"],
            owner_id=owner["id"],
        )
        game_before = _game_state(db)
        ledger_before = db.execute(
            "SELECT COUNT(*) FROM xp_ledger"
        ).fetchone()[0]

        assigned = assign_relationship_manager(
            db,
            lead["id"],
            actor=owner,
            relationship_manager_user_id=junmar["id"],
        )
        assert (
            assigned["business_development_owner_user_id"]
            == junmar["id"]
        )
        assert _game_state(db) == game_before
        assert (
            db.execute("SELECT COUNT(*) FROM xp_ledger").fetchone()[0]
            == ledger_before
        )

        event = db.execute(
            """
            SELECT event_type
            FROM quest_updates
            WHERE task_id = ?
              AND event_type = 'crm_relationship_owner'
            ORDER BY id DESC
            LIMIT 1
            """,
            (lead["quest_id"],),
        ).fetchone()
        assert event["event_type"] == "crm_relationship_owner"

        disabled = set_user_active(
            db,
            target_user_id=junmar["id"],
            acting_user_id=owner["id"],
            active=False,
        )
        assert disabled["active"] == 0
        cleared = get_lead(db, lead["id"])
        assert cleared["business_development_owner_user_id"] is None


def test_playbook_assignment_is_private_role_scoped_and_safe(
    relationship_database,
):
    owner = relationship_database["owner"]
    junmar = relationship_database["junmar"]
    brother = relationship_database["brother"]
    markdown = (
        "# Junmar Sales Playbook\n\n"
        "**Approved introduction**\n\n"
        "<script>alert('not allowed')</script>\n\n"
        "- [ ] Record the next action\n"
    )

    with database.get_db() as db:
        playbook = upsert_playbook(
            db,
            slug="Junmar Sales Playbook",
            title="Junmar Sales Playbook",
            markdown_content=markdown,
            created_by_user_id=owner["id"],
        )
        assign_playbook_to_user(
            db,
            playbook_id=playbook["id"],
            user_id=junmar["id"],
        )

        with pytest.raises(ValueError):
            assign_playbook_to_user(
                db,
                playbook_id=playbook["id"],
                user_id=brother["id"],
            )

        assigned = get_primary_playbook_for_user(
            db,
            junmar["id"],
        )
        assert assigned["slug"] == "junmar-sales-playbook"

        rendered = str(render_markdown_safely(markdown))
        assert "<h1>Junmar Sales Playbook</h1>" in rendered
        assert "<strong>Approved introduction</strong>" in rendered
        assert "<script>" not in rendered
        assert "&lt;script&gt;" in rendered
        assert "☐ Record the next action" in rendered


def test_relationship_home_renders_assigned_playbook_and_queues(
    relationship_database,
):
    owner = relationship_database["owner"]
    junmar = relationship_database["junmar"]

    with database.get_db() as db:
        playbook = upsert_playbook(
            db,
            slug="junmar-home",
            title="Junmar Home Playbook",
            markdown_content="# Home Playbook\nUse approved wording only.",
            created_by_user_id=owner["id"],
        )
        assign_playbook_to_user(
            db,
            playbook_id=playbook["id"],
            user_id=junmar["id"],
        )
        lead = _create(
            db,
            company="Dashboard Relationship",
            creator_id=owner["id"],
            owner_id=owner["id"],
            relationship_manager_id=junmar["id"],
        )
        db.execute(
            """
            UPDATE leads
            SET research_status = 'approved',
                outreach_approved_by_user_id = ?,
                outreach_approved_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (owner["id"], lead["id"]),
        )

        dashboard = load_relationship_manager_dashboard(db, junmar)
        assert dashboard["playbook"]["title"] == "Junmar Home Playbook"
        assert "<h1>Home Playbook</h1>" in str(
            dashboard["playbook"]["rendered_content"]
        )
        queues = {
            queue["key"]: queue
            for queue in dashboard["queues"]
        }
        assert lead["id"] in {
            row["id"]
            for row in queues["ready_outreach"]["leads"]
        }

    request = _request()
    request.state.current_user = junmar
    response = relationship_manager_home(request)
    body = response.body.decode("utf-8")
    assert response.status_code == 200
    assert "Junmar Home Playbook" in body
    assert "Approved outreach" in body
    assert "do not mark a lead Contacted yet" in body


def test_internal_playbook_source_is_git_ignored():
    project_root = Path(__file__).resolve().parent.parent
    gitignore = (project_root / ".gitignore").read_text(encoding="utf-8")
    importer = (project_root / "tools/import_playbook.py").read_text(
        encoding="utf-8"
    )

    assert "private_playbooks/" in gitignore
    assert "--assign-username" in importer
    assert "The Markdown source remains outside Git." in importer
