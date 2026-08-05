from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import database
from app.services.lead_pipeline_workflow import change_pipeline_stage
from app.services.lead_research_permissions import LeadPermissionError
from app.services.leads import create_lead
from app.services.playbooks import (
    assign_playbook_to_user,
    upsert_playbook,
)
from app.services.relationship_manager import (
    load_relationship_manager_dashboard,
    update_next_action_for_actor,
)
from app.services.team_users import (
    create_relationship_manager,
    get_primary_owner_id,
)


REQUIRED_TABLES = {
    "playbooks",
    "user_playbook_assignments",
}
REQUIRED_LEAD_COLUMN = "business_development_owner_user_id"
REQUIRED_LEAD_INDEX = "idx_leads_business_development_owner"


class VerificationFailure(RuntimeError):
    pass


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _online_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_db = _connect(source)
    destination_db = _connect(destination)
    try:
        source_db.backup(destination_db)
    finally:
        destination_db.close()
        source_db.close()


def _integrity(path: Path) -> dict[str, Any]:
    db = _connect(path)
    try:
        return {
            "quick_check": db.execute(
                "PRAGMA quick_check"
            ).fetchone()[0],
            "foreign_key_errors": [
                tuple(row)
                for row in db.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
            ],
        }
    finally:
        db.close()


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return (
        db.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table,),
        ).fetchone()
        is not None
    )


def _stable_snapshot(path: Path) -> dict[str, Any]:
    db = _connect(path)
    try:
        snapshot: dict[str, Any] = {}
        if _table_exists(db, "users"):
            snapshot["users"] = [
                tuple(row)
                for row in db.execute(
                    """
                    SELECT
                        id,
                        username,
                        display_name,
                        password_hash,
                        role,
                        active,
                        must_change_password,
                        session_version,
                        last_login_at,
                        created_at,
                        updated_at
                    FROM users
                    ORDER BY id
                    """
                ).fetchall()
            ]
        if _table_exists(db, "leads"):
            snapshot["leads"] = [
                tuple(row)
                for row in db.execute(
                    """
                    SELECT
                        id,
                        quest_id,
                        created_by_user_id,
                        assigned_to_user_id,
                        request_key,
                        request_fingerprint,
                        dedupe_key,
                        company,
                        contact_person,
                        job_title,
                        source,
                        source_url,
                        problem_opportunity,
                        why_mark_fits,
                        pipeline_status,
                        priority,
                        next_action,
                        next_action_due_date,
                        notes,
                        created_at,
                        updated_at,
                        deleted_at,
                        researched_by_user_id,
                        research_status,
                        submitted_for_review_at,
                        reviewed_by_user_id,
                        reviewed_at,
                        review_notes,
                        outreach_approved_by_user_id,
                        outreach_approved_at
                    FROM leads
                    ORDER BY id
                    """
                ).fetchall()
            ]
        if _table_exists(db, "tasks"):
            snapshot["tasks"] = [
                tuple(row)
                for row in db.execute(
                    """
                    SELECT id, user_id, title, status, progress,
                           xp_reward, created_at, updated_at
                    FROM tasks
                    ORDER BY id
                    """
                ).fetchall()
            ]
        if _table_exists(db, "game_state"):
            snapshot["game_state"] = [
                tuple(row)
                for row in db.execute(
                    """
                    SELECT id, user_id, level, xp_total,
                           xp_into_level, last_level_up_at
                    FROM game_state
                    ORDER BY id
                    """
                ).fetchall()
            ]
        if _table_exists(db, "xp_ledger"):
            snapshot["xp_ledger"] = [
                tuple(row)
                for row in db.execute(
                    """
                    SELECT id, user_id, task_id, event_key, event_type,
                           source_type, source_id, source_title, xp_delta,
                           level_before, level_after, reason, created_at
                    FROM xp_ledger
                    ORDER BY id
                    """
                ).fetchall()
            ]
        return snapshot
    finally:
        db.close()


def _assert_integrity(label: str, report: dict[str, Any]) -> None:
    if report["quick_check"] != "ok":
        raise VerificationFailure(
            f"{label} quick_check did not return ok."
        )
    if report["foreign_key_errors"]:
        raise VerificationFailure(
            f"{label} contains foreign-key errors."
        )


def _schema_checks(path: Path) -> dict[str, Any]:
    db = _connect(path)
    try:
        tables = {
            row["name"]
            for row in db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }
        missing_tables = sorted(REQUIRED_TABLES - tables)
        if missing_tables:
            raise VerificationFailure(
                "Missing playbook tables: "
                + ", ".join(missing_tables)
            )

        lead_columns = {
            row["name"]: row
            for row in db.execute(
                "PRAGMA table_info(leads)"
            ).fetchall()
        }
        relationship_column = lead_columns.get(
            REQUIRED_LEAD_COLUMN
        )
        if relationship_column is None:
            raise VerificationFailure(
                "Missing business-development owner column."
            )
        if (
            relationship_column["type"].upper() != "INTEGER"
            or relationship_column["notnull"]
            or relationship_column["dflt_value"] is not None
        ):
            raise VerificationFailure(
                "Business-development owner column has an "
                "incompatible definition."
            )

        indexes = {
            row["name"]
            for row in db.execute(
                "PRAGMA index_list(leads)"
            ).fetchall()
        }
        if REQUIRED_LEAD_INDEX not in indexes:
            raise VerificationFailure(
                "Missing Relationship Manager lead index."
            )

        users_sql = db.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'users'
            """
        ).fetchone()["sql"]
        normalized = " ".join(users_sql.lower().split())
        normalized = normalized.replace("( ", "(").replace(" )", ")")
        expected_role_check = (
            "check(role in ('owner', 'member', 'lead_sourcer', "
            "'relationship_manager'))"
        )
        if expected_role_check not in normalized:
            raise VerificationFailure(
                "Users role constraint does not include "
                "relationship_manager."
            )

        return {
            "required_tables": sorted(REQUIRED_TABLES),
            "lead_column": REQUIRED_LEAD_COLUMN,
            "lead_index": REQUIRED_LEAD_INDEX,
            "user_role_constraint": "passed",
        }
    finally:
        db.close()


def _game_snapshot(db: sqlite3.Connection) -> tuple[list[tuple], list[tuple]]:
    game_state = [
        tuple(row)
        for row in db.execute(
            """
            SELECT id, user_id, level, xp_total,
                   xp_into_level, last_level_up_at
            FROM game_state
            ORDER BY id
            """
        ).fetchall()
    ]
    xp_ledger = [
        tuple(row)
        for row in db.execute(
            """
            SELECT id, user_id, task_id, event_key, event_type,
                   source_type, source_id, source_title, xp_delta,
                   level_before, level_after, reason, created_at
            FROM xp_ledger
            ORDER BY id
            """
        ).fetchall()
    ]
    return game_state, xp_ledger


def _workflow_canary(path: Path) -> dict[str, Any]:
    database.DB_PATH = path
    unique = _stamp().casefold()

    with database.get_db() as db:
        owner_id = get_primary_owner_id(db, active_only=True)
        if owner_id is None:
            raise VerificationFailure(
                "A live Owner account is required for the canary."
            )
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
        game_before, ledger_before = _game_snapshot(db)

        manager = create_relationship_manager(
            db,
            username="release-rm-" + unique[-12:],
            display_name="Phase 6.1J Release Manager",
            password="release-manager-pass-123",
            password_confirmation="release-manager-pass-123",
        )
        playbook = upsert_playbook(
            db,
            slug="phase-6-1j-release-canary-" + unique,
            title="Phase 6.1J Release Canary",
            markdown_content=(
                "# Release Canary\n"
                "Use approved wording and escalate pricing to Mark."
            ),
            created_by_user_id=owner_id,
        )
        assign_playbook_to_user(
            db,
            playbook_id=playbook["id"],
            user_id=manager["id"],
        )
        lead = create_lead(
            db,
            company="Phase 6.1J Canary " + unique,
            contact_person="Release Verifier",
            job_title="Test Contact",
            source="Staging canary",
            source_url="https://example.com/phase-6-1j-canary",
            problem_opportunity=(
                "Verify Relationship Manager ownership on a copy."
            ),
            why_mark_fits="This is a staging-only verification lead.",
            pipeline_status="new",
            priority="low",
            next_action="Verify relationship ownership.",
            next_action_due_date=None,
            notes="Created only in the staging copy.",
            request_key="phase-6-1j-canary-" + unique,
            created_by_user_id=manager["id"],
            assigned_to_user_id=owner_id,
            business_development_owner_user_id=manager["id"],
        ).lead
        updated = update_next_action_for_actor(
            db,
            lead["id"],
            actor=manager,
            next_action="Hand qualified opportunity to Mark.",
            next_action_due_date=None,
        )

        with_approval_denied = False
        try:
            change_pipeline_stage(
                db,
                lead["id"],
                actor=manager,
                pipeline_status="contacted",
            )
        except LeadPermissionError:
            with_approval_denied = True

        dashboard = load_relationship_manager_dashboard(
            db,
            manager,
        )
        visible_ids = {
            row["id"]
            for queue in dashboard["queues"]
            for row in queue["leads"]
        }

        game_after, ledger_after = _game_snapshot(db)
        if game_after != game_before or ledger_after != ledger_before:
            raise VerificationFailure(
                "The Relationship Manager canary changed XP state."
            )
        if not with_approval_denied:
            raise VerificationFailure(
                "Relationship Manager was able to mark Contacted."
            )
        if updated["business_development_owner_user_id"] != manager["id"]:
            raise VerificationFailure(
                "Canary lead lost its business-development owner."
            )
        if dashboard["playbook"] is None:
            raise VerificationFailure(
                "Assigned playbook did not load on the dashboard."
            )

        # A New lead with no approval belongs in Waiting for Mark,
        # therefore it should be visible in one of the dashboard queues.
        if lead["id"] not in visible_ids:
            raise VerificationFailure(
                "Canary lead is missing from the Relationship Manager dashboard."
            )

        return {
            "owner_id": owner_id,
            "relationship_manager_id": manager["id"],
            "playbook_id": playbook["id"],
            "lead_id": lead["id"],
            "pipeline_status": updated["pipeline_status"],
            "contacted_blocked": with_approval_denied,
            "playbook_loaded": True,
            "xp_unchanged": True,
        }


def _health_check(url: str | None) -> dict[str, Any]:
    if not url:
        return {"status": "skipped"}
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MARK-OS-Phase-6.1J-Verifier"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status != 200:
                raise VerificationFailure(
                    f"Health URL returned HTTP {response.status}."
                )
            return {
                "status": "passed",
                "http_status": response.status,
                "body": body,
            }
    except Exception as exc:
        raise VerificationFailure(
            f"Health check failed: {exc}"
        ) from exc


def _run_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q"]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise VerificationFailure("The full pytest suite failed.")
    return {
        "status": "passed",
        "command": " ".join(command),
    }


def _git_metadata() -> dict[str, str]:
    def value(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    return {
        "branch": value("branch", "--show-current"),
        "commit": value("rev-parse", "HEAD"),
        "status": value("status", "--porcelain"),
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Verify Phase 6.1J by migrating and exercising an online "
            "SQLite backup copy. The source database is never written."
        )
    )
    parser.add_argument("--source-db", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".phase_6_1j_release"),
    )
    parser.add_argument("--health-url", default=None)
    parser.add_argument("--run-tests", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source_db.expanduser().resolve()
    if not source.is_file():
        print(f"ERROR: source database not found: {source}", file=sys.stderr)
        return 1

    run_dir = args.output_dir.expanduser().resolve() / _stamp()
    staging = run_dir / "mark_os_phase_6_1j_staging.db"
    report_path = run_dir / "phase_6_1j_verification.json"
    report: dict[str, Any] = {
        "phase": "6.1J",
        "status": "running",
        "source_database": str(source),
        "staging_database": str(staging),
        "started_at_utc": _stamp(),
        "git": _git_metadata(),
    }

    try:
        source_integrity = _integrity(source)
        _assert_integrity("Source database", source_integrity)
        report["source_integrity"] = source_integrity
        report["source_sha256_before"] = _sha256(source)

        _online_backup(source, staging)
        report["staging_sha256_before"] = _sha256(staging)
        before = _stable_snapshot(staging)

        staging_integrity = _integrity(staging)
        _assert_integrity("Staging copy", staging_integrity)
        report["staging_integrity_before"] = staging_integrity

        database.DB_PATH = staging
        database.init_db()
        database.init_db()

        after = _stable_snapshot(staging)
        if after != before:
            changed = sorted(
                key
                for key in set(before) | set(after)
                if before.get(key) != after.get(key)
            )
            raise VerificationFailure(
                "Stable production data changed during migration: "
                + ", ".join(changed)
            )
        report["stable_data_preserved"] = sorted(before)
        report["schema"] = _schema_checks(staging)
        report["workflow_canary"] = _workflow_canary(staging)

        final_integrity = _integrity(staging)
        _assert_integrity("Final staging copy", final_integrity)
        report["staging_integrity_final"] = final_integrity
        report["source_sha256_after"] = _sha256(source)
        if report["source_sha256_after"] != report["source_sha256_before"]:
            raise VerificationFailure(
                "The source database checksum changed."
            )

        report["health"] = _health_check(args.health_url)
        report["tests"] = (
            _run_tests() if args.run_tests else {"status": "skipped"}
        )
        report["status"] = "passed"
        report["completed_at_utc"] = _stamp()
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        report["completed_at_utc"] = _stamp()
        run_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"FAILED: {exc}", file=sys.stderr)
        print(f"Report: {report_path}", file=sys.stderr)
        return 1

    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print("Phase 6.1J verification PASSED")
    print(f"Source:  {source}")
    print(f"Staging: {staging}")
    print(f"Report:  {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
