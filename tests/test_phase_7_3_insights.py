from __future__ import annotations

from datetime import date
from pathlib import Path

from app import database
from app.db.organizations import organization_id_by_slug
from app.services.insights import build_insights
from app.services.leads import create_lead
from app.services.team_users import create_lead_sourcer


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _actor(user, organization_id):
    return {
        **dict(user),
        "current_workspace": {
            "id": organization_id,
            "slug": "mark-agency",
            "name": "MARK Agency",
            "membership_role": "crm_contributor",
        },
    }


def test_crm_insights_reuse_lead_visibility_and_do_not_mutate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "insights.db")
    _configure_owner(monkeypatch)
    database.init_db()
    with database.get_db() as db:
        organization_id = organization_id_by_slug(db, "mark-agency")
        first = create_lead_sourcer(
            db,
            username="first",
            display_name="First",
            password="temporary-pass-123",
            password_confirmation="temporary-pass-123",
        )
        second = create_lead_sourcer(
            db,
            username="second",
            display_name="Second",
            password="temporary-pass-456",
            password_confirmation="temporary-pass-456",
        )
        for creator, company, source in (
            (first, "Visible Insight Co", "Referral"),
            (second, "Private Insight Co", "LinkedIn"),
        ):
            create_lead(
                db,
                company=company,
                contact_person="Buyer",
                source=source,
                problem_opportunity="Needs reporting",
                why_mark_fits="MARK OS can help",
                next_action="Research",
                created_by_user_id=creator["id"],
                assigned_to_user_id=creator["id"],
                organization_id=organization_id,
            )
        before = {
            "leads": [tuple(row) for row in db.execute("SELECT * FROM leads ORDER BY id")],
            "tasks": [tuple(row) for row in db.execute("SELECT * FROM tasks ORDER BY id")],
            "game": [tuple(row) for row in db.execute("SELECT * FROM game_state ORDER BY id")],
        }
        insights = build_insights(
            db, _actor(first, organization_id), today=date(2026, 9, 3)
        )
        after = {
            "leads": [tuple(row) for row in db.execute("SELECT * FROM leads ORDER BY id")],
            "tasks": [tuple(row) for row in db.execute("SELECT * FROM tasks ORDER BY id")],
            "game": [tuple(row) for row in db.execute("SELECT * FROM game_state ORDER BY id")],
        }

    assert insights["crm"]["lead_count"] == 1
    assert insights["crm"]["sources"] == {"labels": ["Referral"], "values": [1]}
    assert insights["personal"] is None
    assert after == before


def test_chartjs_is_pinned_and_canvas_has_accessible_fallback_label():
    template = (
        Path(__file__).resolve().parents[1] / "app/templates/insights.html"
    ).read_text()
    assert "chart.js@4.4.7" in template
    assert 'aria-label="Pipeline lead counts"' in template
    assert 'role="img"' in template
