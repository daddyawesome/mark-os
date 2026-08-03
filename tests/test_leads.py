import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app import database
from app.services.leads import (
    PIPELINE_STATUSES,
    PRIORITIES,
    create_lead,
    delete_lead,
    get_crm_dashboard_metrics,
    get_lead,
    get_lead_by_quest,
    list_leads,
    update_lead,
    update_lead_next_action,
    update_lead_pipeline,
)
from app.services.quests import (
    complete_quest as complete_linked_quest,
    set_quest_status,
    update_quest_progress,
)


@pytest.fixture
def lead_database(tmp_path, monkeypatch):
    database_path = tmp_path / "leads.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()
    return database_path


def lead_payload(suffix="one", **overrides):
    payload = {
        "company": f"Acme {suffix}",
        "contact_person": f"Alex {suffix}",
        "job_title": "Founder",
        "source": "LinkedIn",
        "source_url": f"https://example.com/leads/{suffix}",
        "problem_opportunity": "Needs a reliable operations dashboard",
        "why_mark_fits": "Mark can design and ship the complete workflow",
        "pipeline_status": "new",
        "priority": "medium",
        "next_action": "Send a concise introduction",
        "next_action_due_date": "2026-08-10",
        "notes": "Warm introduction available",
        "request_key": f"lead-request-{suffix}",
    }
    payload.update(overrides)
    return payload


def row_dict(row):
    return dict(row) if row is not None else None


def test_create_read_list_and_linked_quest_contract(lead_database):
    with database.get_db() as db:
        result = create_lead(
            db,
            **lead_payload(
                source_url=(
                    "HTTPS://EXAMPLE.COM:443/leads/one/?utm_source=test&b=2&a=1#top"
                )
            ),
        )

        assert result.created is True
        assert result.duplicate is False
        assert result.lead["source_url"] == "https://example.com/leads/one?a=1&b=2"
        assert result.lead["request_fingerprint"].startswith("v1:")
        assert len(result.lead["request_fingerprint"]) == 67
        assert result.lead["quest_id"] == result.quest["id"]
        assert result.quest["title"] == (
            "Client: Acme one — Send a concise introduction"
        )
        assert "Alex one, Founder at Acme one" in result.quest["description"]
        assert "reliable operations dashboard" in result.quest["description"]
        assert result.quest["status"] == "backlog"
        assert result.quest["progress"] == 0
        assert result.quest["priority"] == 6
        assert result.quest["due_date"] == "2026-08-10"
        assert result.quest["difficulty"] == "normal"
        assert result.quest["xp_reward"] == 0
        assert result.quest["quest_source"] == "client_hunting"
        assert result.quest["why"] == lead_payload()["why_mark_fits"]

        assert get_lead(db, result.lead["id"])["id"] == result.lead["id"]
        assert get_lead_by_quest(db, result.quest["id"])["id"] == result.lead["id"]
        assert [row["id"] for row in list_leads(db)] == [result.lead["id"]]
        assert [row["id"] for row in list_leads(db, priority="MEDIUM")] == [
            result.lead["id"]
        ]
        assert [row["id"] for row in list_leads(db, pipeline_status="NEW")] == [
            result.lead["id"]
        ]

        update = db.execute(
            "SELECT * FROM quest_updates WHERE task_id = ?",
            (result.quest["id"],),
        ).fetchone()
        assert update["event_type"] == "crm_created"
        assert update["progress"] == 0


def test_general_pipeline_and_next_action_updates_sync_the_quest(lead_database):
    with database.get_db() as db:
        created = create_lead(db, **lead_payload())
        lead_id = created.lead["id"]
        quest_id = created.quest["id"]

        updated = update_lead(
            db,
            lead_id,
            company="Better Co",
            contact_person="Blair Rivera",
            job_title="COO",
            source="Referral",
            source_url="https://better.example/opportunity/",
            problem_opportunity="Manual handoffs are losing client context",
            why_mark_fits="Mark has built this exact operations pattern",
            priority="high",
            notes="Decision maker",
        )
        assert updated["company"] == "Better Co"
        assert updated["contact_person"] == "Blair Rivera"
        assert updated["source_url"] == "https://better.example/opportunity"
        assert updated["notes"] == "Decision maker"

        pipeline = update_lead_pipeline(db, lead_id, pipeline_status="proposal")
        assert pipeline["pipeline_status"] == "proposal"
        next_action = update_lead_next_action(
            db,
            lead_id,
            next_action="Send the final scope",
            next_action_due_date="2026-08-12",
        )
        assert next_action["next_action"] == "Send the final scope"
        assert next_action["next_action_due_date"] == "2026-08-12"

        quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
        assert quest["title"] == "Client: Better Co — Send the final scope"
        assert "Blair Rivera, COO at Better Co" in quest["description"]
        assert "Manual handoffs" in quest["description"]
        assert quest["status"] == "active"
        assert quest["progress"] == 85
        assert quest["priority"] == 10
        assert quest["due_date"] == "2026-08-12"
        assert quest["why"] == "Mark has built this exact operations pattern"

        events = db.execute(
            "SELECT event_type, note FROM quest_updates WHERE task_id = ? ORDER BY id",
            (quest_id,),
        ).fetchall()
        assert [event["event_type"] for event in events] == [
            "crm_created",
            "crm_updated",
            "crm_pipeline",
            "crm_next_action",
        ]
        assert "new to proposal" in events[-2]["note"]
        assert "Send the final scope" in events[-1]["note"]


@pytest.mark.parametrize(
    ("pipeline_status", "quest_status", "progress"),
    [
        ("new", "backlog", 0),
        ("reviewed", "backlog", 10),
        ("contacted", "active", 25),
        ("replied", "active", 45),
        ("meeting", "active", 65),
        ("proposal", "active", 85),
        ("won", "closed", 100),
        ("lost", "closed", 0),
    ],
)
def test_every_pipeline_stage_maps_to_quest_state(
    lead_database,
    pipeline_status,
    quest_status,
    progress,
):
    with database.get_db() as db:
        created = create_lead(
            db,
            **lead_payload(pipeline_status, pipeline_status=pipeline_status),
        )
        quest = db.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (created.quest["id"],),
        ).fetchone()
        assert quest["status"] == quest_status
        assert quest["progress"] == progress
        assert quest["completed_at"] is None


@pytest.mark.parametrize(
    ("priority", "quest_priority"),
    [("high", 10), ("medium", 6), ("low", 3)],
)
def test_every_crm_priority_maps_to_quest_priority(
    lead_database,
    priority,
    quest_priority,
):
    with database.get_db() as db:
        created = create_lead(db, **lead_payload(priority, priority=priority))
        assert created.lead["priority"] == priority
        assert created.quest["priority"] == quest_priority


def test_exported_enum_contract_is_exact():
    assert PIPELINE_STATUSES == (
        "new",
        "reviewed",
        "contacted",
        "replied",
        "meeting",
        "proposal",
        "won",
        "lost",
    )
    assert PRIORITIES == ("high", "medium", "low")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("company", "   ", "Company is required"),
        ("contact_person", "", "Contact person is required"),
        ("source", "", "Source is required"),
        ("problem_opportunity", "", "Problem or opportunity is required"),
        ("why_mark_fits", "", "Why Mark fits is required"),
        ("next_action", "", "Next action is required"),
        ("pipeline_status", "qualified", "Unsupported lead pipeline status"),
        ("priority", "urgent", "Unsupported lead priority"),
        ("source_url", "ftp://example.com/lead", "valid http or https"),
        ("source_url", "https://exa mple.com/lead", "valid http or https"),
        ("source_url", "https://user:pass@example.com", "embedded credentials"),
        ("next_action_due_date", "08/10/2026", "YYYY-MM-DD"),
        ("next_action_due_date", "20260810", "YYYY-MM-DD"),
        ("company", "x" * 201, "200 characters or fewer"),
        ("next_action", "x" * 501, "500 characters or fewer"),
        ("request_key", "x" * 256, "255 characters or fewer"),
    ],
)
def test_create_validation_rejects_bad_values(
    lead_database,
    field,
    value,
    message,
):
    with database.get_db() as db:
        with pytest.raises(ValueError, match=message):
            create_lead(db, **lead_payload(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("request_key", 123, "Request key must be text"),
        ("source_url", 123, "Source URL must be text"),
        ("next_action_due_date", 20260810, "due date must be text"),
        ("pipeline_status", None, "pipeline status must be text"),
        ("priority", None, "priority must be text"),
    ],
)
def test_type_validation_raises_value_error(
    lead_database,
    field,
    value,
    message,
):
    with database.get_db() as db:
        with pytest.raises(ValueError, match=message):
            create_lead(db, **lead_payload(**{field: value}))


def test_request_retry_and_semantic_duplicate_protection(lead_database):
    with database.get_db() as db:
        first = create_lead(db, **lead_payload())
        retry = create_lead(
            db,
            **lead_payload(
                company="  Acme   one ",
                contact_person="Alex one",
                source_url="https://EXAMPLE.com:443/leads/one/#fragment",
                request_key=" lead-request-one ",
            ),
        )
        semantic_duplicate = create_lead(
            db,
            **lead_payload(
                company="ACME ONE",
                contact_person="ALEX ONE",
                source_url=(
                    "https://example.com/leads/one?utm_campaign=ignored#fragment"
                ),
                request_key="different-request",
            ),
        )

        assert retry.duplicate is True
        assert semantic_duplicate.duplicate is True
        assert retry.lead["id"] == first.lead["id"]
        assert semantic_duplicate.lead["id"] == first.lead["id"]
        assert db.execute("SELECT COUNT(*) AS count FROM leads").fetchone()["count"] == 1
        assert db.execute(
            "SELECT COUNT(*) AS count FROM tasks WHERE quest_source = 'client_hunting'"
        ).fetchone()["count"] == 1

        with pytest.raises(ValueError, match="different lead"):
            create_lead(
                db,
                **lead_payload(
                    company="Different Company",
                    request_key="lead-request-one",
                ),
            )

        with pytest.raises(ValueError, match="different lead payload"):
            create_lead(
                db,
                **lead_payload(
                    priority="high",
                    request_key="lead-request-one",
                ),
            )


def test_original_request_retry_survives_later_lead_edits(lead_database):
    original_payload = lead_payload()
    with database.get_db() as db:
        created = create_lead(db, **original_payload)
        original_fingerprint = created.lead["request_fingerprint"]
        update_lead_pipeline(db, created.lead["id"], pipeline_status="meeting")
        update_lead_next_action(
            db,
            created.lead["id"],
            next_action="Run the discovery call",
            next_action_due_date="2026-08-19",
        )

        retry = create_lead(db, **original_payload)

        assert retry.duplicate is True
        assert retry.lead["id"] == created.lead["id"]
        assert retry.lead["pipeline_status"] == "meeting"
        assert retry.lead["next_action"] == "Run the discovery call"
        assert retry.lead["request_fingerprint"] == original_fingerprint
        assert db.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1


def test_failed_lead_insert_rolls_back_the_linked_quest(lead_database):
    with database.get_db() as db:
        before_tasks = db.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()[
            "count"
        ]
        db.execute(
            """
            CREATE TRIGGER reject_lead_insert
            BEFORE INSERT ON leads
            BEGIN
                SELECT RAISE(ABORT, 'test lead insert failure');
            END
            """
        )

        with pytest.raises(sqlite3.IntegrityError, match="test lead insert failure"):
            create_lead(db, **lead_payload())

        assert db.execute("SELECT COUNT(*) AS count FROM leads").fetchone()["count"] == 0
        assert db.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()[
            "count"
        ] == before_tasks


def test_caller_transaction_owns_the_final_rollback(lead_database):
    with pytest.raises(RuntimeError, match="caller rollback"):
        with database.get_db() as db:
            create_lead(db, **lead_payload())
            raise RuntimeError("caller rollback")

    with database.get_db() as db:
        assert db.execute("SELECT COUNT(*) AS count FROM leads").fetchone()["count"] == 0
        assert db.execute(
            "SELECT COUNT(*) AS count FROM tasks WHERE quest_source = 'client_hunting'"
        ).fetchone()["count"] == 0


def _thread_connection(database_path):
    db = sqlite3.connect(database_path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def test_concurrent_disjoint_updates_preserve_both_changes(lead_database):
    with database.get_db() as db:
        lead_id = create_lead(db, **lead_payload()).lead["id"]

    start = Barrier(2)

    def change_pipeline():
        db = _thread_connection(lead_database)
        try:
            start.wait(timeout=5)
            update_lead_pipeline(db, lead_id, pipeline_status="meeting")
            db.commit()
        finally:
            db.close()

    def change_next_action():
        db = _thread_connection(lead_database)
        try:
            start.wait(timeout=5)
            update_lead_next_action(
                db,
                lead_id,
                next_action="Prepare discovery questions",
                next_action_due_date="2026-08-18",
            )
            db.commit()
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(change_pipeline), executor.submit(change_next_action)]
        for future in futures:
            future.result(timeout=15)

    with database.get_db() as db:
        lead = get_lead(db, lead_id)
        assert lead["pipeline_status"] == "meeting"
        assert lead["next_action"] == "Prepare discovery questions"
        assert lead["next_action_due_date"] == "2026-08-18"


def test_concurrent_delete_retries_write_one_audit_event(lead_database):
    with database.get_db() as db:
        created = create_lead(db, **lead_payload())
        lead_id = created.lead["id"]
        quest_id = created.quest["id"]

    start = Barrier(2)

    def archive_lead():
        db = _thread_connection(lead_database)
        try:
            start.wait(timeout=5)
            deleted = delete_lead(db, lead_id, confirmed=True)
            db.commit()
            return deleted["id"]
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(archive_lead), executor.submit(archive_lead)]
        assert [future.result(timeout=15) for future in futures] == [lead_id, lead_id]

    with database.get_db() as db:
        assert db.execute(
            """
            SELECT COUNT(*) FROM quest_updates
            WHERE task_id = ? AND event_type = 'crm_deleted'
            """,
            (quest_id,),
        ).fetchone()[0] == 1


@pytest.mark.parametrize("operation", ["pipeline", "next_action"])
def test_specialized_update_and_audit_event_are_atomic(lead_database, operation):
    event_type = "crm_pipeline" if operation == "pipeline" else "crm_next_action"
    with database.get_db() as db:
        created = create_lead(db, **lead_payload())
        db.execute(
            f"""
            CREATE TRIGGER reject_special_event
            BEFORE INSERT ON quest_updates
            WHEN NEW.event_type = '{event_type}'
            BEGIN
                SELECT RAISE(ABORT, 'test audit failure');
            END
            """
        )

        with pytest.raises(sqlite3.IntegrityError, match="test audit failure"):
            if operation == "pipeline":
                update_lead_pipeline(
                    db,
                    created.lead["id"],
                    pipeline_status="meeting",
                )
            else:
                update_lead_next_action(
                    db,
                    created.lead["id"],
                    next_action="Book the discovery call",
                    next_action_due_date="2026-08-15",
                )

        lead = get_lead(db, created.lead["id"])
        quest = db.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (created.quest["id"],),
        ).fetchone()
        assert lead["pipeline_status"] == "new"
        assert lead["next_action"] == "Send a concise introduction"
        assert lead["next_action_due_date"] == "2026-08-10"
        assert quest["status"] == "backlog"
        assert quest["progress"] == 0
        assert quest["title"] == (
            "Client: Acme one — Send a concise introduction"
        )


def test_identity_collision_update_is_atomic(lead_database):
    with database.get_db() as db:
        first = create_lead(db, **lead_payload("first"))
        second = create_lead(db, **lead_payload("second"))
        second_before = row_dict(second.lead)
        quest_before = row_dict(second.quest)

        with pytest.raises(ValueError, match="already has this identity"):
            update_lead(
                db,
                second.lead["id"],
                company=first.lead["company"],
                contact_person=first.lead["contact_person"],
                source_url=first.lead["source_url"],
            )

        assert row_dict(get_lead(db, second.lead["id"])) == second_before
        assert row_dict(
            db.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (second.quest["id"],),
            ).fetchone()
        ) == quest_before


def test_dashboard_metrics_count_only_active_leads(lead_database):
    with database.get_db() as db:
        created = [
            create_lead(db, **lead_payload("new", priority="high")),
            create_lead(
                db,
                **lead_payload("contacted", pipeline_status="contacted", priority="high"),
            ),
            create_lead(db, **lead_payload("replied", pipeline_status="replied")),
            create_lead(
                db,
                **lead_payload("meeting", pipeline_status="meeting", priority="low"),
            ),
            create_lead(
                db,
                **lead_payload("proposal", pipeline_status="proposal", priority="high"),
            ),
            create_lead(db, **lead_payload("won", pipeline_status="won")),
            create_lead(
                db,
                **lead_payload("lost", pipeline_status="lost", priority="low"),
            ),
        ]
        delete_lead(db, created[0].lead["id"], confirmed=True)

        assert get_crm_dashboard_metrics(db) == {
            "total_leads": 6,
            "high_priority_leads": 2,
            "contacted": 1,
            "replies": 1,
            "meetings": 1,
            "proposals": 1,
            "won_clients": 1,
        }


def test_soft_delete_requires_confirmation_and_allows_semantic_re_add(lead_database):
    with database.get_db() as db:
        created = create_lead(db, **lead_payload())
        with pytest.raises(ValueError, match="requires confirmation"):
            delete_lead(db, created.lead["id"])
        assert get_lead(db, created.lead["id"]) is not None

        deleted = delete_lead(db, created.lead["id"], confirmed=True)
        assert deleted["deleted_at"] is not None
        assert get_lead(db, created.lead["id"]) is None
        assert get_lead(db, created.lead["id"], include_deleted=True) is not None
        assert get_lead_by_quest(db, created.quest["id"]) is None
        assert (
            get_lead_by_quest(db, created.quest["id"], include_deleted=True)["id"]
            == created.lead["id"]
        )
        quest = db.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (created.quest["id"],),
        ).fetchone()
        assert quest["status"] == "abandoned"
        assert quest["progress"] == 0

        replacement = create_lead(
            db,
            **lead_payload(request_key="replacement-request"),
        )
        assert replacement.created is True
        assert replacement.lead["id"] != created.lead["id"]
        assert replacement.quest["id"] != created.quest["id"]
        assert len(list_leads(db)) == 1
        assert len(list_leads(db, include_deleted=True)) == 2

        with pytest.raises(ValueError, match="deleted lead"):
            create_lead(db, **lead_payload(request_key="lead-request-one"))


def test_crm_mutations_do_not_award_or_reverse_xp(lead_database):
    with database.get_db() as db:
        game_state_before = row_dict(
            db.execute(
                """
                SELECT level, xp_total, xp_into_level, last_level_up_at
                FROM game_state WHERE id = 1
                """
            ).fetchone()
        )
        ledger_before = [
            row_dict(row)
            for row in db.execute("SELECT * FROM xp_ledger ORDER BY id").fetchall()
        ]

        created = create_lead(db, **lead_payload())
        for pipeline_status in PIPELINE_STATUSES:
            update_lead_pipeline(
                db,
                created.lead["id"],
                pipeline_status=pipeline_status,
            )
        delete_lead(db, created.lead["id"], confirmed=True)

        game_state_after = row_dict(
            db.execute(
                """
                SELECT level, xp_total, xp_into_level, last_level_up_at
                FROM game_state WHERE id = 1
                """
            ).fetchone()
        )
        ledger_after = [
            row_dict(row)
            for row in db.execute("SELECT * FROM xp_ledger ORDER BY id").fetchall()
        ]
        assert game_state_after == game_state_before
        assert ledger_after == ledger_before


def test_linked_quest_rejects_non_crm_service_mutations(lead_database):
    with database.get_db() as db:
        created = create_lead(db, **lead_payload())
        quest_id = created.quest["id"]

        with pytest.raises(ValueError, match="managed through the CRM"):
            set_quest_status(db, quest_id=quest_id, status="active")
        with pytest.raises(ValueError, match="managed through the CRM"):
            update_quest_progress(
                db,
                quest_id=quest_id,
                note="Bypass CRM",
                progress=50,
            )
        with pytest.raises(ValueError, match="managed through the CRM"):
            complete_linked_quest(
                db,
                quest_id=quest_id,
                result_notes="Bypass CRM",
            )

        quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
        assert quest["status"] == "backlog"
        assert quest["progress"] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM xp_ledger WHERE task_id = ?", (quest_id,)
        ).fetchone()[0] == 0


def test_crm_lifecycle_leaves_existing_life_os_records_unchanged(lead_database):
    with database.get_db() as db:
        existing_records = {
            "tasks": [
                row_dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM tasks
                    WHERE quest_source != 'client_hunting'
                    ORDER BY id
                    """
                ).fetchall()
            ],
            "game_state": [
                row_dict(row)
                for row in db.execute("SELECT * FROM game_state ORDER BY id").fetchall()
            ],
            "xp_ledger": [
                row_dict(row)
                for row in db.execute("SELECT * FROM xp_ledger ORDER BY id").fetchall()
            ],
            "checkins": [
                row_dict(row)
                for row in db.execute("SELECT * FROM checkins ORDER BY id").fetchall()
            ],
            "memories": [
                row_dict(row)
                for row in db.execute("SELECT * FROM memories ORDER BY id").fetchall()
            ],
        }

        created = create_lead(db, **lead_payload())
        update_lead_pipeline(db, created.lead["id"], pipeline_status="won")
        update_lead_next_action(
            db,
            created.lead["id"],
            next_action="Prepare the kickoff",
            next_action_due_date="2026-08-20",
        )
        delete_lead(db, created.lead["id"], confirmed=True)

        assert [
            row_dict(row)
            for row in db.execute(
                """
                SELECT * FROM tasks
                WHERE quest_source != 'client_hunting'
                ORDER BY id
                """
            ).fetchall()
        ] == existing_records["tasks"]
        for table_name in ("game_state", "xp_ledger", "checkins", "memories"):
            current = [
                row_dict(row)
                for row in db.execute(
                    f"SELECT * FROM {table_name} ORDER BY id"
                ).fetchall()
            ]
            assert current == existing_records[table_name]
