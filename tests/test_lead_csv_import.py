from __future__ import annotations

import pytest

from app import database
from app.services.lead_csv_import import (
    CSV_HEADERS,
    LeadCsvImportError,
    import_leads_from_csv,
    lead_csv_template_bytes,
    preview_leads_from_csv,
)


def _csv_bytes(rows: list[list[str]], headers: tuple[str, ...] = CSV_HEADERS) -> bytes:
    import csv
    import io

    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def _valid_rows() -> list[list[str]]:
    return [
        [
            "Northstar Analytics",
            "Ada Reyes",
            "Founder",
            "LinkedIn",
            "https://example.com/northstar",
            "Reporting is slow and difficult to trust.",
            "Python, SQL, and Power BI delivery experience.",
            "New",
            "High",
            "Send a focused introduction",
            "2026-08-05",
            "Warm signal from a public post.",
        ],
        [
            "Blue Harbor Studio",
            "Leo Cruz",
            "Operations Lead",
            "Referral",
            "",
            "Manual spreadsheets delay weekly decisions.",
            "Excel automation and dashboard experience.",
            "Reviewed",
            "Medium",
            "Prepare a one-page audit offer",
            "2026-08-06",
            "",
        ],
    ]


def test_template_contains_expected_headers():
    content = lead_csv_template_bytes().decode("utf-8-sig").strip()
    assert content.splitlines()[0].split(",") == list(CSV_HEADERS)


def test_csv_import_creates_leads_and_linked_zero_xp_quests(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "lead-import.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    content = _csv_bytes(_valid_rows())

    with database.get_db() as db:
        first = import_leads_from_csv(db, content)

    assert first.total_rows == 2
    assert first.created_count == 2
    assert first.duplicate_count == 0
    assert first.invalid_count == 0

    with database.get_db() as db:
        leads = db.execute(
            "SELECT company, pipeline_status, priority, quest_id FROM leads ORDER BY id"
        ).fetchall()
        quests = db.execute(
            """
            SELECT id, quest_source, xp_reward
            FROM tasks
            WHERE quest_source = 'client_hunting'
            ORDER BY id
            """
        ).fetchall()
        xp_count = db.execute("SELECT COUNT(*) FROM xp_ledger").fetchone()[0]

    assert [row["company"] for row in leads] == [
        "Northstar Analytics",
        "Blue Harbor Studio",
    ]
    assert [(row["pipeline_status"], row["priority"]) for row in leads] == [
        ("new", "high"),
        ("reviewed", "medium"),
    ]
    assert [row["quest_id"] for row in leads] == [row["id"] for row in quests]
    assert all(row["quest_source"] == "client_hunting" for row in quests)
    assert all(row["xp_reward"] == 0 for row in quests)
    assert xp_count == 0

    with database.get_db() as db:
        repeated = import_leads_from_csv(db, content)
        lead_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        quest_count = db.execute(
            "SELECT COUNT(*) FROM tasks WHERE quest_source = 'client_hunting'"
        ).fetchone()[0]

    assert repeated.created_count == 0
    assert repeated.duplicate_count == 2
    assert repeated.invalid_count == 0
    assert lead_count == 2
    assert quest_count == 2


def test_csv_import_reports_invalid_rows_but_keeps_valid_rows(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "partial-import.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    rows = _valid_rows()
    rows.append(
        [
            "",
            "Missing Company",
            "",
            "LinkedIn",
            "",
            "Needs reporting help.",
            "Good fit.",
            "New",
            "High",
            "Send message",
            "2026-08-05",
            "",
        ]
    )

    with database.get_db() as db:
        result = import_leads_from_csv(db, _csv_bytes(rows))
        lead_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    assert result.total_rows == 3
    assert result.created_count == 2
    assert result.invalid_count == 1
    assert result.errors[0].row_number == 4
    assert "Company is required" in result.errors[0].message
    assert lead_count == 2


def test_csv_import_rejects_missing_headers(tmp_path, monkeypatch):
    database_path = tmp_path / "bad-header.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    bad_headers = tuple(header for header in CSV_HEADERS if header != "Why Mark fits")
    content = _csv_bytes([], headers=bad_headers)

    with database.get_db() as db:
        with pytest.raises(LeadCsvImportError, match="Why Mark fits"):
            import_leads_from_csv(db, content)


def test_csv_preview_validates_rows_without_writing(tmp_path, monkeypatch):
    database_path = tmp_path / "preview.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    rows = _valid_rows()
    rows.append(
        [
            "",
            "Missing Company",
            "",
            "LinkedIn",
            "",
            "Needs reporting help.",
            "Good fit.",
            "New",
            "High",
            "Send message",
            "2026-08-05",
            "",
        ]
    )
    content = _csv_bytes(rows)

    with database.get_db() as db:
        lead_count_before = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        preview = preview_leads_from_csv(db, content)
        lead_count_after = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    assert preview.total_rows == 3
    assert preview.valid_count == 2
    assert preview.invalid_count == 1
    assert preview.duplicate_count == 0
    assert lead_count_before == lead_count_after == 0

    invalid = [row for row in preview.rows if row.status == "invalid"]
    assert len(invalid) == 1
    assert invalid[0].row_number == 4
    assert "Company is required" in (invalid[0].message or "")


def test_csv_preview_warns_about_existing_leads(tmp_path, monkeypatch):
    database_path = tmp_path / "preview-duplicate.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    content = _csv_bytes(_valid_rows())

    with database.get_db() as db:
        import_leads_from_csv(db, content)
        preview = preview_leads_from_csv(db, content)
        lead_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    assert lead_count == 2
    assert preview.valid_count == 0
    assert preview.duplicate_count == 2
    assert all(row.status == "duplicate_existing" for row in preview.rows)
    assert all(row.duplicate_lead_id is not None for row in preview.rows)


def test_csv_preview_warns_about_repeated_rows_in_file(tmp_path, monkeypatch):
    database_path = tmp_path / "preview-in-file-duplicate.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    rows = _valid_rows()
    rows.append(rows[0])
    content = _csv_bytes(rows)

    with database.get_db() as db:
        preview = preview_leads_from_csv(db, content)
        lead_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    assert preview.total_rows == 3
    assert preview.valid_count == 2
    assert preview.duplicate_count == 1
    assert lead_count == 0

    duplicate_rows = [
        row for row in preview.rows if row.status == "duplicate_in_file"
    ]
    assert len(duplicate_rows) == 1
    assert duplicate_rows[0].row_number == 4
    assert duplicate_rows[0].duplicate_row_number == 2
