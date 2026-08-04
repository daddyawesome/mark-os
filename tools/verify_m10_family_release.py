from __future__ import annotations

import sqlite3
import uuid

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

from app import database
from app.db import family_integrity, family_workspace
from app.services.access_control import can_access_request


PERSONAL_TABLES = (
    "profile",
    "goals",
    "projects",
    "checkins",
    "directions",
    "game_state",
    "game_history",
    "tasks",
    "quest_updates",
    "xp_ledger",
    "memories",
    "timeline_events",
    "chat_sessions",
    "chat_messages",
    "agent_runs",
    "agent_steps",
)


def _exercise_per_user_uniqueness(
    db: sqlite3.Connection,
    owner_id: int,
    member_id: int,
) -> None:
    suffix = uuid.uuid4().hex
    project_name = f"M10 verification project {suffix}"
    memory_key = f"m10_verification_{suffix}"

    db.execute("SAVEPOINT m10_verify")
    try:
        project_values = (
            project_name,
            "Temporary verification row.",
            "active",
            1,
            0,
            "Rollback this row.",
        )
        for user_id in (owner_id, member_id):
            db.execute(
                """
                INSERT INTO projects (
                    user_id, name, purpose, status,
                    priority, progress, next_action
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, *project_values),
            )

        try:
            db.execute(
                """
                INSERT INTO projects (
                    user_id, name, purpose, status,
                    priority, progress, next_action
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (owner_id, *project_values),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise RuntimeError(
                "Same-user duplicate project names are not blocked."
            )

        memory_values = (
            "verification",
            memory_key,
            "Temporary verification memory.",
            1,
            "m10_verifier",
        )
        for user_id in (owner_id, member_id):
            db.execute(
                """
                INSERT INTO memories (
                    user_id, memory_type, memory_key,
                    memory_value, importance, source
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, *memory_values),
            )

        try:
            db.execute(
                """
                INSERT INTO memories (
                    user_id, memory_type, memory_key,
                    memory_value, importance, source
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (owner_id, *memory_values),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise RuntimeError(
                "Same-user duplicate memory keys are not blocked."
            )
    finally:
        db.execute("ROLLBACK TO m10_verify")
        db.execute("RELEASE m10_verify")


def main() -> None:
    database.init_db()

    with database.get_db() as db:
        users = db.execute(
            """
            SELECT id, username, display_name, role, active
            FROM users
            ORDER BY id
            """
        ).fetchall()
        owner = next(
            (
                row
                for row in users
                if row["role"] == "owner" and bool(row["active"])
            ),
            None,
        )
        if owner is None:
            print(f"Database path: {database.DB_PATH}")
            print("Users found:")
            for row in users:
                print(dict(row))
            raise RuntimeError(
                "M10 verification requires an active owner. "
                "Load .env and initialize the owner before committing."
            )

        family_workspace.ensure_all_workspaces(db)
        family_workspace.validate(db)
        family_integrity.validate_triggers(db)

        print(f"Database path: {database.DB_PATH}")
        print("Personal ownership:")
        for table_name in PERSONAL_TABLES:
            columns = {
                row["name"]
                for row in db.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }
            if "user_id" not in columns:
                raise RuntimeError(
                    f"Missing ownership column: {table_name}.user_id"
                )
            unowned = int(
                db.execute(
                    f"SELECT COUNT(*) FROM {table_name} "
                    "WHERE user_id IS NULL OR user_id = 0"
                ).fetchone()[0]
            )
            orphan = int(
                db.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table_name} AS item
                    LEFT JOIN users AS u ON u.id = item.user_id
                    WHERE item.user_id IS NOT NULL
                      AND u.id IS NULL
                    """
                ).fetchone()[0]
            )
            print(
                f"  {table_name}: unowned={unowned}, orphan={orphan}"
            )
            if unowned or orphan:
                raise RuntimeError(
                    f"Invalid ownership remains in {table_name}."
                )

        member = next(
            (
                row
                for row in users
                if row["role"] == "member" and bool(row["active"])
            ),
            None,
        )
        if member is not None:
            _exercise_per_user_uniqueness(
                db,
                int(owner["id"]),
                int(member["id"]),
            )
            print(
                "Per-user project and memory uniqueness: PASS "
                f"({owner['username']} + {member['username']})"
            )
        else:
            print(
                "Per-user uniqueness runtime probe: SKIPPED "
                "(no active member yet)"
            )

    member_user = {
        "id": 2,
        "username": "member",
        "display_name": "Member",
        "role": "member",
    }
    sourcer_user = {
        "id": 3,
        "username": "sourcer",
        "display_name": "Sourcer",
        "role": "lead_sourcer",
    }
    if not can_access_request(member_user, "GET", "/quests"):
        raise RuntimeError("Members cannot access their personal quests.")
    if can_access_request(member_user, "GET", "/crm"):
        raise RuntimeError("Members can incorrectly access CRM.")
    if not can_access_request(sourcer_user, "GET", "/crm"):
        raise RuntimeError("Lead sourcer CRM access regressed.")
    if can_access_request(sourcer_user, "GET", "/"):
        raise RuntimeError("Lead sourcer can incorrectly access personal OS.")

    print("Role access boundaries: PASS")
    print("PASS: M10 family workspace release verification succeeded.")


if __name__ == "__main__":
    main()
