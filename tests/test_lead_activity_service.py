from __future__ import annotations

import pytest

from app import database
from app.services.lead_activities import (
    LeadActivityNotFoundError,
    LeadActivityPermissionError,
    correct_activity,
    create_activity,
    get_activity,
    list_lead_activities,
    restore_activity,
    soft_delete_activity,
)
from app.services.leads import create_lead


def _configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("MARK_OS_USERNAME", "mark")
    monkeypatch.setenv("MARK_OS_PASSWORD", "owner-password-123")
    monkeypatch.setenv("MARK_OS_DISPLAY_NAME", "Mark")


def _insert_user(
    db,
    *,
    username: str,
    display_name: str,
    role: str,
    active: int = 1,
) -> int:
    return int(
        db.execute(
            """
            INSERT INTO users (
                username,
                display_name,
                password_hash,
                role,
                active
            )
            VALUES (?, ?, 'test-password-hash', ?, ?)
            """,
            (username, display_name, role, active),
        ).lastrowid
    )


def _actor(db, user_id: int) -> dict:
    row = db.execute(
        """
        SELECT id, username, display_name, role, active
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    return dict(row)


@pytest.fixture
def activity_context(tmp_path, monkeypatch):
    path = tmp_path / "phase-6-3b.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    _configure_owner(monkeypatch)
    database.init_db()

    with database.get_db() as db:
        owner_id = int(
            db.execute(
                """
                SELECT id
                FROM users
                WHERE role = 'owner'
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()["id"]
        )
        sourcer_id = _insert_user(
            db,
            username="researcher",
            display_name="Lead Researcher",
            role="lead_sourcer",
        )
        other_sourcer_id = _insert_user(
            db,
            username="other-researcher",
            display_name="Other Researcher",
            role="lead_sourcer",
        )
        relationship_manager_id = _insert_user(
            db,
            username="junmar",
            display_name="Junmar",
            role="relationship_manager",
        )
        member_id = _insert_user(
            db,
            username="family-member",
            display_name="Family Member",
            role="member",
        )
        inactive_id = _insert_user(
            db,
            username="inactive-researcher",
            display_name="Inactive Researcher",
            role="lead_sourcer",
            active=0,
        )

        lead = create_lead(
            db,
            company="Phase 6.3B Company",
            contact_person="Alex Buyer",
            source="LinkedIn",
            source_url="https://example.com/phase-6-3b",
            problem_opportunity="Manual follow-up loses context.",
            why_mark_fits="Mark can build an auditable workflow.",
            next_action="Prepare an approved introduction.",
            request_key="phase-6-3b-visible-lead",
            created_by_user_id=sourcer_id,
            assigned_to_user_id=sourcer_id,
            business_development_owner_user_id=relationship_manager_id,
        ).lead

        other_lead = create_lead(
            db,
            company="Other Researcher's Company",
            contact_person="Taylor Buyer",
            source="Referral",
            problem_opportunity="Follow-up ownership is unclear.",
            why_mark_fits="Mark can implement accountability.",
            next_action="Research the opportunity.",
            request_key="phase-6-3b-other-lead",
            created_by_user_id=other_sourcer_id,
            assigned_to_user_id=other_sourcer_id,
        ).lead

        return {
            "owner_id": owner_id,
            "sourcer_id": sourcer_id,
            "other_sourcer_id": other_sourcer_id,
            "relationship_manager_id": relationship_manager_id,
            "member_id": member_id,
            "inactive_id": inactive_id,
            "lead_id": int(lead["id"]),
            "other_lead_id": int(other_lead["id"]),
        }


def test_owner_creates_attributed_activity_with_canonical_time(
    activity_context,
):
    with database.get_db() as db:
        owner = _actor(db, activity_context["owner_id"])
        activity = create_activity(
            db,
            activity_context["lead_id"],
            actor=owner,
            activity_type="email_sent",
            activity_at="2026-08-06T21:30:15+08:00",
            channel="email",
            message_summary=" Sent an approved introduction. ",
            notes="Used the approved wording.",
            performed_by_user_id=activity_context["sourcer_id"],
            responsible_user_id=activity_context[
                "relationship_manager_id"
            ],
            response_status="awaiting_reply",
            next_follow_up_date="2026-08-09",
        )

        assert activity["activity_at"] == "2026-08-06 13:30:15"
        assert activity["message_summary"] == (
            "Sent an approved introduction."
        )
        assert activity["created_by_user_id"] == activity_context["owner_id"]
        assert activity["performed_by_user_id"] == (
            activity_context["sourcer_id"]
        )
        assert activity["responsible_user_id"] == (
            activity_context["relationship_manager_id"]
        )
        assert activity["created_by_name"] == "Mark"
        assert activity["performed_by_name"] == "Lead Researcher"
        assert activity["responsible_name"] == "Junmar"


def test_database_role_truth_blocks_forged_or_undelegated_staff_activity(
    activity_context,
):
    with database.get_db() as db:
        sourcer = _actor(db, activity_context["sourcer_id"])
        forged_owner = dict(sourcer)
        forged_owner["role"] = "owner"

        research = create_activity(
            db,
            activity_context["lead_id"],
            actor=forged_owner,
            activity_type="research_started",
            activity_at="2026-08-06 09:00:00",
            message_summary="Started account research.",
        )
        assert research["created_by_user_id"] == activity_context["sourcer_id"]

        with pytest.raises(
            LeadActivityPermissionError,
            match="activity type",
        ):
            create_activity(
                db,
                activity_context["lead_id"],
                actor=forged_owner,
                activity_type="email_sent",
                activity_at="2026-08-06 10:00:00",
                channel="email",
                message_summary="Forged outreach event.",
            )

        with pytest.raises(
            LeadActivityPermissionError,
            match="another performer",
        ):
            create_activity(
                db,
                activity_context["lead_id"],
                actor=sourcer,
                activity_type="research_completed",
                activity_at="2026-08-06 10:30:00",
                message_summary="Completed research.",
                performed_by_user_id=activity_context["owner_id"],
            )

        relationship_manager = _actor(
            db,
            activity_context["relationship_manager_id"],
        )
        with pytest.raises(
            LeadActivityPermissionError,
            match="activity type",
        ):
            create_activity(
                db,
                activity_context["lead_id"],
                actor=relationship_manager,
                activity_type="email_sent",
                activity_at="2026-08-06 11:00:00",
                channel="email",
                message_summary="Attempted undelegated outreach.",
            )

        member = _actor(db, activity_context["member_id"])
        with pytest.raises(
            LeadActivityPermissionError,
            match="active CRM role",
        ):
            create_activity(
                db,
                activity_context["lead_id"],
                actor=member,
                activity_type="research_started",
                activity_at="2026-08-06 12:00:00",
                message_summary="Member must not access CRM.",
            )


def test_visibility_uses_same_not_found_result_for_missing_and_foreign_records(
    activity_context,
):
    with database.get_db() as db:
        owner = _actor(db, activity_context["owner_id"])
        activity = create_activity(
            db,
            activity_context["lead_id"],
            actor=owner,
            activity_type="research_started",
            activity_at="2026-08-06 08:00:00",
            message_summary="Owner started review.",
        )

        relationship_manager = _actor(
            db,
            activity_context["relationship_manager_id"],
        )
        assert get_activity(
            db,
            int(activity["id"]),
            actor=relationship_manager,
        )["id"] == activity["id"]

        other_sourcer = _actor(
            db,
            activity_context["other_sourcer_id"],
        )
        for activity_id in (int(activity["id"]), 999_999):
            with pytest.raises(
                LeadActivityNotFoundError,
                match="not found",
            ):
                get_activity(db, activity_id, actor=other_sourcer)

        with pytest.raises(
            LeadActivityNotFoundError,
            match="Lead not found",
        ):
            list_lead_activities(
                db,
                activity_context["lead_id"],
                actor=other_sourcer,
            )


def test_list_is_reverse_chronological_and_deleted_rows_are_owner_only(
    activity_context,
):
    with database.get_db() as db:
        owner = _actor(db, activity_context["owner_id"])
        older = create_activity(
            db,
            activity_context["lead_id"],
            actor=owner,
            activity_type="research_started",
            activity_at="2026-08-06 08:00:00",
            message_summary="Older activity.",
        )
        newer = create_activity(
            db,
            activity_context["lead_id"],
            actor=owner,
            activity_type="research_completed",
            activity_at="2026-08-06 09:00:00",
            message_summary="Newer activity.",
        )
        soft_delete_activity(
            db,
            int(newer["id"]),
            actor=owner,
            correction_reason="Duplicate activity entered by mistake.",
        )

        active_rows = list_lead_activities(
            db,
            activity_context["lead_id"],
            actor=owner,
        )
        assert [row["id"] for row in active_rows] == [older["id"]]

        all_rows = list_lead_activities(
            db,
            activity_context["lead_id"],
            actor=owner,
            include_deleted=True,
        )
        assert [row["id"] for row in all_rows] == [
            newer["id"],
            older["id"],
        ]

        sourcer = _actor(db, activity_context["sourcer_id"])
        with pytest.raises(
            LeadActivityPermissionError,
            match="Owner",
        ):
            list_lead_activities(
                db,
                activity_context["lead_id"],
                actor=sourcer,
                include_deleted=True,
            )


def test_original_author_can_correct_own_research_record_but_not_owner_record(
    activity_context,
):
    with database.get_db() as db:
        sourcer = _actor(db, activity_context["sourcer_id"])
        original = create_activity(
            db,
            activity_context["lead_id"],
            actor=sourcer,
            activity_type="research_started",
            activity_at="2026-08-06 08:00:00",
            message_summary="Started reserch.",
        )
        corrected = correct_activity(
            db,
            int(original["id"]),
            actor=sourcer,
            correction_reason="Corrected a spelling error.",
            message_summary="Started research.",
        )
        assert corrected["created_by_user_id"] == (
            activity_context["sourcer_id"]
        )
        assert corrected["corrected_by_user_id"] == (
            activity_context["sourcer_id"]
        )
        assert corrected["message_summary"] == "Started research."

        owner = _actor(db, activity_context["owner_id"])
        owner_activity = create_activity(
            db,
            activity_context["lead_id"],
            actor=owner,
            activity_type="approved_for_outreach",
            activity_at="2026-08-06 09:00:00",
            message_summary="Owner approved outreach.",
        )
        with pytest.raises(
            LeadActivityPermissionError,
            match="correct",
        ):
            correct_activity(
                db,
                int(owner_activity["id"]),
                actor=sourcer,
                correction_reason="Unauthorized correction.",
                message_summary="Changed owner record.",
            )

        owner_corrected = correct_activity(
            db,
            int(original["id"]),
            actor=owner,
            correction_reason="Corrected performer attribution.",
            performed_by_user_id=activity_context[
                "relationship_manager_id"
            ],
        )
        assert owner_corrected["created_by_user_id"] == (
            activity_context["sourcer_id"]
        )
        assert owner_corrected["corrected_by_user_id"] == (
            activity_context["owner_id"]
        )
        assert owner_corrected["performed_by_user_id"] == (
            activity_context["relationship_manager_id"]
        )


def test_soft_delete_and_owner_restore_keep_auditable_fields(
    activity_context,
):
    with database.get_db() as db:
        sourcer = _actor(db, activity_context["sourcer_id"])
        activity = create_activity(
            db,
            activity_context["lead_id"],
            actor=sourcer,
            activity_type="research_completed",
            activity_at="2026-08-06 10:00:00",
            message_summary="Research completed twice.",
        )
        deleted = soft_delete_activity(
            db,
            int(activity["id"]),
            actor=sourcer,
            correction_reason="Duplicate activity record.",
        )
        assert deleted["deleted_at"] is not None
        assert deleted["corrected_by_user_id"] == (
            activity_context["sourcer_id"]
        )

        with pytest.raises(LeadActivityNotFoundError):
            get_activity(
                db,
                int(activity["id"]),
                actor=sourcer,
            )
        with pytest.raises(LeadActivityNotFoundError):
            get_activity(
                db,
                int(activity["id"]),
                actor=sourcer,
                include_deleted=True,
            )

        owner = _actor(db, activity_context["owner_id"])
        restored = restore_activity(
            db,
            int(activity["id"]),
            actor=owner,
            correction_reason=(
                "Restored after confirming it was not a duplicate."
            ),
        )
        assert restored["deleted_at"] is None
        assert restored["corrected_by_user_id"] == (
            activity_context["owner_id"]
        )
        assert "Restored" in restored["correction_reason"]


@pytest.mark.parametrize(
    ("field_overrides", "message"),
    [
        ({"activity_at": "2026-08-06"}, "ISO 8601"),
        ({"activity_type": "unknown"}, "Unsupported activity"),
        ({"channel": "sms"}, "Unsupported channel"),
        ({"response_status": "maybe"}, "Unsupported response"),
        (
            {
                "next_follow_up_date": "2026-08-10",
                "responsible_user_id": None,
            },
            "responsible CRM user",
        ),
    ],
)
def test_create_validation_rejects_invalid_values_without_partial_insert(
    activity_context,
    field_overrides,
    message,
):
    with database.get_db() as db:
        owner = _actor(db, activity_context["owner_id"])
        before = int(
            db.execute(
                "SELECT COUNT(*) AS item_count FROM lead_activities"
            ).fetchone()["item_count"]
        )
        payload = {
            "actor": owner,
            "activity_type": "research_started",
            "activity_at": "2026-08-06 08:00:00",
            "channel": "internal",
            "message_summary": "Valid summary.",
            "response_status": "not_applicable",
            "next_follow_up_date": None,
            "responsible_user_id": None,
        }
        payload.update(field_overrides)
        with pytest.raises(
            (ValueError, LeadActivityPermissionError),
            match=message,
        ):
            create_activity(
                db,
                activity_context["lead_id"],
                **payload,
            )

        after = int(
            db.execute(
                "SELECT COUNT(*) AS item_count FROM lead_activities"
            ).fetchone()["item_count"]
        )
        assert after == before


def test_responsible_user_must_be_active_crm_user(
    activity_context,
):
    with database.get_db() as db:
        owner = _actor(db, activity_context["owner_id"])
        for invalid_user_id in (
            activity_context["member_id"],
            activity_context["inactive_id"],
        ):
            with pytest.raises(
                ValueError,
                match="active CRM user",
            ):
                create_activity(
                    db,
                    activity_context["lead_id"],
                    actor=owner,
                    activity_type="research_started",
                    activity_at="2026-08-06 08:00:00",
                    message_summary="Invalid responsibility.",
                    responsible_user_id=invalid_user_id,
                )
