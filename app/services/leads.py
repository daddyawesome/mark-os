from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.services.lead_identity import lead_creation_fingerprint

PIPELINE_STATUSES = (
    "new",
    "reviewed",
    "contacted",
    "replied",
    "meeting",
    "proposal",
    "won",
    "lost",
)
PRIORITIES = ("high", "medium", "low")

PRIORITY_VALUES = {"high": 10, "medium": 6, "low": 3}
# A won/lost lead is a reversible CRM outcome, not an immutable Quest Engine
# completion. `closed` keeps terminal leads out of execution queues without
# creating XP, timeline, or result-evidence records.
CRM_CLOSED_QUEST_STATUS = "closed"
PIPELINE_QUEST_STATE = {
    "new": ("backlog", 0),
    "reviewed": ("backlog", 10),
    "contacted": ("active", 25),
    "replied": ("active", 45),
    "meeting": ("active", 65),
    "proposal": ("active", 85),
    "won": (CRM_CLOSED_QUEST_STATUS, 100),
    "lost": (CRM_CLOSED_QUEST_STATUS, 0),
}

MAX_REQUEST_KEY_LENGTH = 255
MAX_COMPANY_LENGTH = 200
MAX_CONTACT_PERSON_LENGTH = 200
MAX_JOB_TITLE_LENGTH = 200
MAX_SOURCE_LENGTH = 200
MAX_SOURCE_URL_LENGTH = 2_000
MAX_PROBLEM_LENGTH = 4_000
MAX_WHY_LENGTH = 4_000
MAX_NEXT_ACTION_LENGTH = 500
MAX_NOTES_LENGTH = 5_000

_UNSET = object()


@dataclass(frozen=True)
class LeadCreateResult:
    lead: sqlite3.Row
    quest: sqlite3.Row
    created: bool

    @property
    def duplicate(self) -> bool:
        return not self.created


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _resolve_organization_id(
    db: sqlite3.Connection,
    value: int | None,
) -> int:
    """Resolve one explicit workspace, with temporary MARK Agency fallback.

    Phase 6.6B-4A keeps legacy internal callers working while every runtime CRM
    caller is migrated to pass the active organization in 6.6B-4B. Even the
    fallback is scoped to MARK Agency; no core lead query remains globally
    unscoped.
    """
    if value is None:
        rows = db.execute(
            "SELECT id FROM organizations WHERE slug = 'mark-agency'"
        ).fetchall()
        if len(rows) != 1:
            raise RuntimeError(
                "Cannot resolve CRM workspace; exactly one mark-agency "
                "organization is required."
            )
        return int(rows[0]["id"])

    safe_organization_id = _positive_id(value, "Organization ID")
    row = db.execute(
        "SELECT id FROM organizations WHERE id = ?",
        (safe_organization_id,),
    ).fetchone()
    if row is None:
        raise ValueError(
            "Organization ID must reference an existing organization"
        )
    return safe_organization_id


def _active_user_id(
    db: sqlite3.Connection,
    value: int | None,
    field_name: str,
) -> int | None:
    if value is None:
        return None
    safe_user_id = _positive_id(value, field_name)
    user = db.execute(
        "SELECT id FROM users WHERE id = ? AND active = 1",
        (safe_user_id,),
    ).fetchone()
    if user is None:
        raise ValueError(f"{field_name} must reference an active user")
    return safe_user_id


def _active_workspace_user_id(
    db: sqlite3.Connection,
    value: int | None,
    field_name: str,
    *,
    organization_id: int,
) -> int | None:
    if value is None:
        return None
    safe_user_id = _positive_id(value, field_name)
    row = db.execute(
        """
        SELECT users.id
        FROM users
        JOIN organization_memberships AS membership
          ON membership.user_id = users.id
         AND membership.organization_id = ?
        WHERE users.id = ?
          AND users.active = 1
          AND membership.active = 1
        """,
        (organization_id, safe_user_id),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"{field_name} must reference an active user in this workspace"
        )
    return safe_user_id


def _required_text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    clean_value = " ".join(value.strip().split())
    if not clean_value:
        raise ValueError(f"{field_name} is required")
    if len(clean_value) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer")
    return clean_value


def _optional_text(value: str | None, field_name: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    clean_value = " ".join(value.strip().split())
    if len(clean_value) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer")
    return clean_value


def _normalize_request_key(request_key: str | None) -> str | None:
    if request_key is not None and not isinstance(request_key, str):
        raise ValueError("Request key must be text")
    clean_key = (request_key or "").strip() or None
    if clean_key and len(clean_key) > MAX_REQUEST_KEY_LENGTH:
        raise ValueError(
            f"Request key must be {MAX_REQUEST_KEY_LENGTH} characters or fewer"
        )
    return clean_key


def _normalize_pipeline_status(pipeline_status: str) -> str:
    if not isinstance(pipeline_status, str):
        raise ValueError("Lead pipeline status must be text")
    clean_status = pipeline_status.strip().lower()
    if clean_status not in PIPELINE_STATUSES:
        raise ValueError(f"Unsupported lead pipeline status: {pipeline_status}")
    return clean_status


def _normalize_priority(priority: str) -> str:
    if not isinstance(priority, str):
        raise ValueError("Lead priority must be text")
    clean_priority = priority.strip().lower()
    if clean_priority not in PRIORITIES:
        raise ValueError(f"Unsupported lead priority: {priority}")
    return clean_priority


def _normalize_date(value: str | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError("Next-action due date must be text")
    clean_value = (value or "").strip() or None
    if clean_value is None:
        return None
    try:
        normalized = date.fromisoformat(clean_value).isoformat()
    except ValueError as exc:
        raise ValueError("Next-action due date must use YYYY-MM-DD") from exc
    if normalized != clean_value:
        raise ValueError("Next-action due date must use YYYY-MM-DD")
    return normalized


def _canonical_source_url(source_url: str | None) -> str:
    if source_url is not None and not isinstance(source_url, str):
        raise ValueError("Source URL must be text")
    clean_url = (source_url or "").strip()
    if not clean_url:
        return ""
    if len(clean_url) > MAX_SOURCE_URL_LENGTH:
        raise ValueError(
            f"Source URL must be {MAX_SOURCE_URL_LENGTH} characters or fewer"
        )
    if any(character.isspace() for character in clean_url):
        raise ValueError("Source URL must be a valid http or https URL")

    parsed = urlsplit(clean_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Source URL must be a valid http or https URL")
    if parsed.username or parsed.password:
        raise ValueError("Source URL cannot contain embedded credentials")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Source URL contains an invalid port") from exc

    hostname = parsed.hostname.casefold()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parsed.path.rstrip("/")
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
    ]
    query = urlencode(sorted(query_items))
    return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def _dedupe_part(value: str) -> str:
    return " ".join(value.casefold().split())


def _lead_dedupe_key(
    *,
    company: str,
    contact_person: str,
    source: str,
    source_url: str,
) -> str:
    identity = "\x1f".join(
        (
            _dedupe_part(company),
            _dedupe_part(contact_person),
            source_url or _dedupe_part(source),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _normalize_lead_fields(
    *,
    company: str,
    contact_person: str,
    source: str,
    problem_opportunity: str,
    why_mark_fits: str,
    next_action: str,
    job_title: str = "",
    source_url: str = "",
    pipeline_status: str = "new",
    priority: str = "medium",
    next_action_due_date: str | None = None,
    notes: str = "",
) -> dict[str, str | None]:
    clean_company = _required_text(company, "Company", MAX_COMPANY_LENGTH)
    clean_contact = _required_text(
        contact_person,
        "Contact person",
        MAX_CONTACT_PERSON_LENGTH,
    )
    clean_source = _required_text(source, "Source", MAX_SOURCE_LENGTH)
    clean_url = _canonical_source_url(source_url)
    values: dict[str, str | None] = {
        "company": clean_company,
        "contact_person": clean_contact,
        "job_title": _optional_text(job_title, "Job title", MAX_JOB_TITLE_LENGTH),
        "source": clean_source,
        "source_url": clean_url,
        "problem_opportunity": _required_text(
            problem_opportunity,
            "Problem or opportunity",
            MAX_PROBLEM_LENGTH,
        ),
        "why_mark_fits": _required_text(
            why_mark_fits,
            "Why Mark fits",
            MAX_WHY_LENGTH,
        ),
        "pipeline_status": _normalize_pipeline_status(pipeline_status),
        "priority": _normalize_priority(priority),
        "next_action": _required_text(
            next_action,
            "Next action",
            MAX_NEXT_ACTION_LENGTH,
        ),
        "next_action_due_date": _normalize_date(next_action_due_date),
        "notes": _optional_text(notes, "Notes", MAX_NOTES_LENGTH),
    }
    values["dedupe_key"] = _lead_dedupe_key(
        company=clean_company,
        contact_person=clean_contact,
        source=clean_source,
        source_url=clean_url,
    )
    return values


def normalize_lead_field_values(
    *,
    company: str,
    contact_person: str,
    source: str,
    problem_opportunity: str,
    why_mark_fits: str,
    next_action: str,
    job_title: str = "",
    source_url: str = "",
    pipeline_status: str = "new",
    priority: str = "medium",
    next_action_due_date: str | None = None,
    notes: str = "",
) -> dict[str, str | None]:
    """Validate and normalize lead fields without writing to the database."""
    return _normalize_lead_fields(
        company=company,
        contact_person=contact_person,
        job_title=job_title,
        source=source,
        source_url=source_url,
        problem_opportunity=problem_opportunity,
        why_mark_fits=why_mark_fits,
        pipeline_status=pipeline_status,
        priority=priority,
        next_action=next_action,
        next_action_due_date=next_action_due_date,
        notes=notes,
    )


@contextmanager
def _write_unit(db: sqlite3.Connection) -> Iterator[None]:
    # Read-after-lock prevents two requests from deriving full lead/quest state
    # from stale snapshots and then overwriting each other's unrelated changes.
    # The surrounding get_db() context still owns the final commit or rollback.
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    else:
        # A caller may already own a deferred transaction. A no-row write safely
        # acquires SQLite's write reservation before this service reads state.
        db.execute("UPDATE leads SET id = id WHERE 0")
    db.execute("SAVEPOINT lead_service_write")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK TO SAVEPOINT lead_service_write")
        db.execute("RELEASE SAVEPOINT lead_service_write")
        raise
    else:
        db.execute("RELEASE SAVEPOINT lead_service_write")


def get_lead(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    include_deleted: bool = False,
    organization_id: int | None = None,
) -> sqlite3.Row | None:
    safe_lead_id = _positive_id(lead_id, "Lead ID")
    safe_organization_id = _resolve_organization_id(db, organization_id)
    deleted_condition = "" if include_deleted else "AND l.deleted_at IS NULL"
    return db.execute(
        f"""
        SELECT
            l.*,
            creator.display_name AS created_by_name,
            creator.username AS created_by_username,
            assignee.display_name AS assigned_to_name,
            assignee.username AS assigned_to_username,
            relationship_manager.display_name AS business_development_owner_name,
            relationship_manager.username AS business_development_owner_username
        FROM leads AS l
        LEFT JOIN users AS creator ON creator.id = l.created_by_user_id
        LEFT JOIN users AS assignee ON assignee.id = l.assigned_to_user_id
        LEFT JOIN users AS relationship_manager
          ON relationship_manager.id = l.business_development_owner_user_id
        WHERE l.id = ?
          AND l.organization_id = ?
          {deleted_condition}
        """,
        (safe_lead_id, safe_organization_id),
    ).fetchone()

def get_lead_by_quest(
    db: sqlite3.Connection,
    quest_id: int,
    *,
    include_deleted: bool = False,
    organization_id: int | None = None,
) -> sqlite3.Row | None:
    safe_quest_id = _positive_id(quest_id, "Quest ID")
    safe_organization_id = _resolve_organization_id(db, organization_id)
    deleted_condition = "" if include_deleted else "AND deleted_at IS NULL"
    return db.execute(
        f"""
        SELECT *
        FROM leads
        WHERE quest_id = ?
          AND organization_id = ?
          {deleted_condition}
        """,
        (safe_quest_id, safe_organization_id),
    ).fetchone()

def _require_lead(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    include_deleted: bool = False,
    organization_id: int | None = None,
) -> sqlite3.Row:
    lead = get_lead(
        db,
        lead_id,
        include_deleted=include_deleted,
        organization_id=organization_id,
    )
    if not lead:
        raise ValueError("Lead not found")
    return lead

def _get_quest(db: sqlite3.Connection, quest_id: int) -> sqlite3.Row:
    quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
    if not quest:
        raise RuntimeError("Lead's linked quest was not found")
    return quest


def _lead_result(
    db: sqlite3.Connection,
    lead: sqlite3.Row,
    *,
    created: bool,
) -> LeadCreateResult:
    return LeadCreateResult(
        lead=lead,
        quest=_get_quest(db, lead["quest_id"]),
        created=created,
    )


def _get_lead_by_request_key(
    db: sqlite3.Connection,
    request_key: str,
) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM leads WHERE request_key = ?",
        (request_key,),
    ).fetchone()


def _get_active_lead_by_dedupe_key(
    db: sqlite3.Connection,
    dedupe_key: str,
    *,
    organization_id: int | None = None,
) -> sqlite3.Row | None:
    safe_organization_id = _resolve_organization_id(db, organization_id)
    return db.execute(
        """
        SELECT *
        FROM leads
        WHERE organization_id = ?
          AND dedupe_key = ?
          AND deleted_at IS NULL
        """,
        (safe_organization_id, dedupe_key),
    ).fetchone()

def find_active_lead_by_dedupe_key(
    db: sqlite3.Connection,
    dedupe_key: str,
    *,
    organization_id: int | None = None,
) -> sqlite3.Row | None:
    return _get_active_lead_by_dedupe_key(
        db,
        dedupe_key,
        organization_id=organization_id,
    )

def _existing_create_result(
    db: sqlite3.Connection,
    *,
    organization_id: int,
    request_key: str | None,
    values: dict[str, str | None],
) -> LeadCreateResult | None:
    if request_key:
        by_request = _get_lead_by_request_key(db, request_key)
        if by_request:
            if int(by_request["organization_id"]) != organization_id:
                # Request keys remain globally unique for backward-compatible
                # idempotency, but a retry must never return another workspace's
                # lead.
                raise ValueError("Request key was already used")
            if by_request["deleted_at"] is not None:
                raise ValueError("Request key belongs to a deleted lead")
            if by_request["request_fingerprint"] != lead_creation_fingerprint(values):
                raise ValueError(
                    "Request key was already used with a different lead payload"
                )
            return _lead_result(db, by_request, created=False)
    by_identity = _get_active_lead_by_dedupe_key(
        db,
        str(values["dedupe_key"]),
        organization_id=organization_id,
    )
    if by_identity:
        return _lead_result(db, by_identity, created=False)
    return None

def _crm_quest_owner_id(
    db: sqlite3.Connection,
    preferred_user_id: int | None,
) -> int | None:
    if preferred_user_id is not None:
        preferred = db.execute(
            """
            SELECT id
            FROM users
            WHERE id = ?
              AND role = 'owner'
              AND active = 1
            """,
            (preferred_user_id,),
        ).fetchone()
        if preferred is not None:
            return int(preferred["id"])

    owner = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner' AND active = 1
        ORDER BY id
        LIMIT 1
        """
    ).fetchone()
    if owner is None:
        # Ownerless legacy/test databases use the temporary ownership
        # marker 0. M8 backfills this to the real owner later.
        return 0
    return int(owner["id"])


def _quest_title(values: dict[str, str | None]) -> str:
    return f"Client: {values['company']} — {values['next_action']}"


def _quest_description(values: dict[str, str | None]) -> str:
    role = f", {values['job_title']}" if values["job_title"] else ""
    location = str(values["source_url"] or values["source"])
    return (
        f"Client lead: {values['contact_person']}{role} at {values['company']}. "
        f"Source: {location}. Problem/opportunity: {values['problem_opportunity']}."
    )


def _insert_quest(
    db: sqlite3.Connection,
    values: dict[str, str | None],
    *,
    user_id: int | None,
) -> sqlite3.Row:
    task_status, progress = PIPELINE_QUEST_STATE[str(values["pipeline_status"])]
    cursor = db.execute(
        """
        INSERT INTO tasks
            (user_id, title, description, status, priority, energy_required, due_date,
             difficulty, xp_reward, progress, quest_source, why,
             started_at, completed_at, updated_at)
        VALUES
            (?, ?, ?, ?, ?, 3, ?, 'normal', 0, ?, 'client_hunting', ?,
             CASE WHEN ? IN ('active', 'closed') THEN CURRENT_TIMESTAMP END,
             NULL,
             CURRENT_TIMESTAMP)
        """,
        (
            user_id,
            _quest_title(values),
            _quest_description(values),
            task_status,
            PRIORITY_VALUES[str(values["priority"])],
            values["next_action_due_date"],
            progress,
            values["why_mark_fits"],
            task_status,
        ),
    )
    return _get_quest(db, cursor.lastrowid)


def _record_quest_update(
    db: sqlite3.Connection,
    *,
    quest_id: int,
    event_type: str,
    note: str,
    progress: int,
) -> None:
    db.execute(
        """
        INSERT INTO quest_updates (
            user_id,
            task_id,
            note,
            progress,
            event_type
        )
        SELECT user_id, id, ?, ?, ?
        FROM tasks
        WHERE id = ?
        """,
        (note.strip(), progress, event_type, quest_id),
    )


def create_lead(
    db: sqlite3.Connection,
    *,
    company: str,
    contact_person: str,
    source: str,
    problem_opportunity: str,
    why_mark_fits: str,
    next_action: str,
    job_title: str = "",
    source_url: str = "",
    pipeline_status: str = "new",
    priority: str = "medium",
    next_action_due_date: str | None = None,
    notes: str = "",
    request_key: str | None = None,
    created_by_user_id: int | None = None,
    assigned_to_user_id: int | None = None,
    business_development_owner_user_id: int | None = None,
    organization_id: int | None = None,
) -> LeadCreateResult:
    clean_request_key = _normalize_request_key(request_key)
    safe_organization_id = _resolve_organization_id(db, organization_id)
    if organization_id is None:
        safe_creator_id = _active_user_id(
            db, created_by_user_id, "Created-by user ID"
        )
        safe_assignee_id = _active_user_id(
            db, assigned_to_user_id, "Assigned-to user ID"
        )
        safe_relationship_manager_id = _active_user_id(
            db,
            business_development_owner_user_id,
            "Business-development owner user ID",
        )
    else:
        safe_creator_id = _active_workspace_user_id(
            db,
            created_by_user_id,
            "Created-by user ID",
            organization_id=safe_organization_id,
        )
        safe_assignee_id = _active_workspace_user_id(
            db,
            assigned_to_user_id,
            "Assigned-to user ID",
            organization_id=safe_organization_id,
        )
        safe_relationship_manager_id = _active_workspace_user_id(
            db,
            business_development_owner_user_id,
            "Business-development owner user ID",
            organization_id=safe_organization_id,
        )
    if safe_relationship_manager_id is not None:
        relationship_manager = db.execute(
            """
            SELECT role
            FROM users
            WHERE id = ? AND active = 1
            """,
            (safe_relationship_manager_id,),
        ).fetchone()
        if (
            relationship_manager is None
            or relationship_manager["role"] != "relationship_manager"
        ):
            raise ValueError(
                "Business-development owner must be an active "
                "Relationship Manager."
            )
    values = _normalize_lead_fields(
        company=company,
        contact_person=contact_person,
        job_title=job_title,
        source=source,
        source_url=source_url,
        problem_opportunity=problem_opportunity,
        why_mark_fits=why_mark_fits,
        pipeline_status=pipeline_status,
        priority=priority,
        next_action=next_action,
        next_action_due_date=next_action_due_date,
        notes=notes,
    )

    try:
        with _write_unit(db):
            duplicate = _existing_create_result(
                db,
                organization_id=safe_organization_id,
                request_key=clean_request_key,
                values=values,
            )
            if duplicate:
                return duplicate
            quest_owner_id = _crm_quest_owner_id(
                db,
                safe_assignee_id,
            )
            quest = _insert_quest(
                db,
                values,
                user_id=quest_owner_id,
            )
            cursor = db.execute(
                """
                INSERT INTO leads
                    (organization_id, quest_id, created_by_user_id,
                     assigned_to_user_id,
                     business_development_owner_user_id,
                     request_key, request_fingerprint, dedupe_key,
                     company, contact_person, job_title, source, source_url,
                     problem_opportunity,
                     why_mark_fits, pipeline_status, priority, next_action,
                     next_action_due_date, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    safe_organization_id,
                    quest["id"],
                    safe_creator_id,
                    safe_assignee_id,
                    safe_relationship_manager_id,
                    clean_request_key,
                    lead_creation_fingerprint(values),
                    values["dedupe_key"],
                    values["company"],
                    values["contact_person"],
                    values["job_title"],
                    values["source"],
                    values["source_url"],
                    values["problem_opportunity"],
                    values["why_mark_fits"],
                    values["pipeline_status"],
                    values["priority"],
                    values["next_action"],
                    values["next_action_due_date"],
                    values["notes"],
                ),
            )
            lead_id = cursor.lastrowid
            _, progress = PIPELINE_QUEST_STATE[str(values["pipeline_status"])]
            _record_quest_update(
                db,
                quest_id=quest["id"],
                event_type="crm_created",
                note=(
                    f"CRM lead created for {values['contact_person']} at "
                    f"{values['company']}; next action: {values['next_action']}."
                ),
                progress=progress,
            )
    except sqlite3.IntegrityError:
        duplicate = _existing_create_result(
            db,
            organization_id=safe_organization_id,
            request_key=clean_request_key,
            values=values,
        )
        if duplicate:
            return duplicate
        raise

    lead = get_lead(
        db,
        lead_id,
        organization_id=safe_organization_id,
    )
    if not lead:
        raise RuntimeError("Created lead could not be reloaded")
    return _lead_result(db, lead, created=True)

def list_leads(
    db: sqlite3.Connection,
    *,
    pipeline_status: str | None = None,
    priority: str | None = None,
    created_by_user_id: int | None = None,
    include_deleted: bool = False,
    organization_id: int | None = None,
) -> list[sqlite3.Row]:
    safe_organization_id = _resolve_organization_id(db, organization_id)
    conditions = ["l.organization_id = ?"]
    parameters: list[object] = [safe_organization_id]
    if not include_deleted:
        conditions.append("l.deleted_at IS NULL")
    if pipeline_status is not None:
        conditions.append("l.pipeline_status = ?")
        parameters.append(_normalize_pipeline_status(pipeline_status))
    if priority is not None:
        conditions.append("l.priority = ?")
        parameters.append(_normalize_priority(priority))
    if created_by_user_id is not None:
        conditions.append("l.created_by_user_id = ?")
        parameters.append(_positive_id(created_by_user_id, "Created-by user ID"))
    where = f"WHERE {' AND '.join(conditions)}"
    return db.execute(
        f"""
        SELECT
            l.*,
            creator.display_name AS created_by_name,
            creator.username AS created_by_username,
            assignee.display_name AS assigned_to_name,
            assignee.username AS assigned_to_username,
            relationship_manager.display_name AS business_development_owner_name,
            relationship_manager.username AS business_development_owner_username
        FROM leads AS l
        LEFT JOIN users AS creator ON creator.id = l.created_by_user_id
        LEFT JOIN users AS assignee ON assignee.id = l.assigned_to_user_id
        LEFT JOIN users AS relationship_manager
          ON relationship_manager.id = l.business_development_owner_user_id
        {where}
        ORDER BY
            CASE l.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
            CASE l.pipeline_status
                WHEN 'proposal' THEN 0 WHEN 'meeting' THEN 1
                WHEN 'replied' THEN 2 WHEN 'contacted' THEN 3
                WHEN 'reviewed' THEN 4 WHEN 'new' THEN 5
                WHEN 'won' THEN 6 ELSE 7
            END,
            COALESCE(l.next_action_due_date, '9999-12-31'),
            l.updated_at DESC,
            l.id DESC
        """,
        parameters,
    ).fetchall()

def _values_from_update(
    current: sqlite3.Row,
    *,
    company: str | None,
    contact_person: str | None,
    job_title: str | None,
    source: str | None,
    source_url: str | None,
    problem_opportunity: str | None,
    why_mark_fits: str | None,
    pipeline_status: str | None,
    priority: str | None,
    next_action: str | None,
    next_action_due_date: str | None | object,
    notes: str | None,
) -> dict[str, str | None]:
    return _normalize_lead_fields(
        company=current["company"] if company is None else company,
        contact_person=(
            current["contact_person"] if contact_person is None else contact_person
        ),
        job_title=current["job_title"] if job_title is None else job_title,
        source=current["source"] if source is None else source,
        source_url=current["source_url"] if source_url is None else source_url,
        problem_opportunity=(
            current["problem_opportunity"]
            if problem_opportunity is None
            else problem_opportunity
        ),
        why_mark_fits=(
            current["why_mark_fits"] if why_mark_fits is None else why_mark_fits
        ),
        pipeline_status=(
            current["pipeline_status"]
            if pipeline_status is None
            else pipeline_status
        ),
        priority=current["priority"] if priority is None else priority,
        next_action=current["next_action"] if next_action is None else next_action,
        next_action_due_date=(
            current["next_action_due_date"]
            if next_action_due_date is _UNSET
            else next_action_due_date
        ),
        notes=current["notes"] if notes is None else notes,
    )


def _sync_quest(
    db: sqlite3.Connection,
    *,
    quest_id: int,
    values: dict[str, str | None],
) -> None:
    task_status, progress = PIPELINE_QUEST_STATE[str(values["pipeline_status"])]
    cursor = db.execute(
        """
        UPDATE tasks
        SET title = ?, description = ?, status = ?, priority = ?, due_date = ?,
            difficulty = 'normal', xp_reward = 0, progress = ?,
            quest_source = 'client_hunting', why = ?,
            started_at = CASE
                WHEN ? IN ('active', 'closed') THEN COALESCE(started_at, CURRENT_TIMESTAMP)
                ELSE started_at
            END,
            completed_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            _quest_title(values),
            _quest_description(values),
            task_status,
            PRIORITY_VALUES[str(values["priority"])],
            values["next_action_due_date"],
            progress,
            values["why_mark_fits"],
            task_status,
            quest_id,
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("Lead's linked quest could not be updated")


def _changed_fields(current: sqlite3.Row, values: dict[str, str | None]) -> list[str]:
    return [
        name
        for name, value in values.items()
        if name != "dedupe_key" and current[name] != value
    ]


def _persist_lead_update(
    db: sqlite3.Connection,
    *,
    current: sqlite3.Row,
    values: dict[str, str | None],
    event_type: str = "crm_updated",
    event_note: str | None = None,
) -> sqlite3.Row:
    changed = _changed_fields(current, values)
    if not changed:
        return current

    organization_id = int(current["organization_id"])
    try:
        cursor = db.execute(
            """
            UPDATE leads
            SET dedupe_key = ?, company = ?, contact_person = ?, job_title = ?,
                source = ?, source_url = ?, problem_opportunity = ?,
                why_mark_fits = ?, pipeline_status = ?, priority = ?,
                next_action = ?, next_action_due_date = ?, notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
            """,
            (
                values["dedupe_key"],
                values["company"],
                values["contact_person"],
                values["job_title"],
                values["source"],
                values["source_url"],
                values["problem_opportunity"],
                values["why_mark_fits"],
                values["pipeline_status"],
                values["priority"],
                values["next_action"],
                values["next_action_due_date"],
                values["notes"],
                current["id"],
                organization_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Lead not found")
        _sync_quest(db, quest_id=current["quest_id"], values=values)
        _, progress = PIPELINE_QUEST_STATE[str(values["pipeline_status"])]
        _record_quest_update(
            db,
            quest_id=current["quest_id"],
            event_type=event_type,
            note=event_note or f"CRM lead updated: {', '.join(changed)}.",
            progress=progress,
        )
    except sqlite3.IntegrityError as exc:
        duplicate = _get_active_lead_by_dedupe_key(
            db,
            str(values["dedupe_key"]),
            organization_id=organization_id,
        )
        if duplicate and duplicate["id"] != current["id"]:
            raise ValueError("An active lead already has this identity") from exc
        raise

    updated = get_lead(
        db,
        current["id"],
        organization_id=organization_id,
    )
    if not updated:
        raise RuntimeError("Updated lead could not be reloaded")
    return updated

def update_lead(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    company: str | None = None,
    contact_person: str | None = None,
    job_title: str | None = None,
    source: str | None = None,
    source_url: str | None = None,
    problem_opportunity: str | None = None,
    why_mark_fits: str | None = None,
    pipeline_status: str | None = None,
    priority: str | None = None,
    next_action: str | None = None,
    next_action_due_date: str | None | object = _UNSET,
    notes: str | None = None,
    organization_id: int | None = None,
) -> sqlite3.Row:
    safe_lead_id = _positive_id(lead_id, "Lead ID")
    safe_organization_id = _resolve_organization_id(db, organization_id)
    with _write_unit(db):
        current = _require_lead(
            db,
            safe_lead_id,
            organization_id=safe_organization_id,
        )
        values = _values_from_update(
            current,
            company=company,
            contact_person=contact_person,
            job_title=job_title,
            source=source,
            source_url=source_url,
            problem_opportunity=problem_opportunity,
            why_mark_fits=why_mark_fits,
            pipeline_status=pipeline_status,
            priority=priority,
            next_action=next_action,
            next_action_due_date=next_action_due_date,
            notes=notes,
        )
        return _persist_lead_update(db, current=current, values=values)


def update_lead_pipeline(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    pipeline_status: str,
    organization_id: int | None = None,
) -> sqlite3.Row:
    safe_lead_id = _positive_id(lead_id, "Lead ID")
    safe_organization_id = _resolve_organization_id(db, organization_id)
    clean_status = _normalize_pipeline_status(pipeline_status)
    with _write_unit(db):
        current = _require_lead(
            db,
            safe_lead_id,
            organization_id=safe_organization_id,
        )
        if current["pipeline_status"] == clean_status:
            return current
        values = _values_from_update(
            current,
            company=None,
            contact_person=None,
            job_title=None,
            source=None,
            source_url=None,
            problem_opportunity=None,
            why_mark_fits=None,
            pipeline_status=clean_status,
            priority=None,
            next_action=None,
            next_action_due_date=_UNSET,
            notes=None,
        )
        return _persist_lead_update(
            db,
            current=current,
            values=values,
            event_type="crm_pipeline",
            event_note=(
                f"CRM pipeline changed from {current['pipeline_status']} to "
                f"{clean_status}."
            ),
        )


def update_lead_next_action(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    next_action: str,
    next_action_due_date: str | None = None,
    organization_id: int | None = None,
) -> sqlite3.Row:
    safe_lead_id = _positive_id(lead_id, "Lead ID")
    safe_organization_id = _resolve_organization_id(db, organization_id)
    with _write_unit(db):
        current = _require_lead(
            db,
            safe_lead_id,
            organization_id=safe_organization_id,
        )
        values = _values_from_update(
            current,
            company=None,
            contact_person=None,
            job_title=None,
            source=None,
            source_url=None,
            problem_opportunity=None,
            why_mark_fits=None,
            pipeline_status=None,
            priority=None,
            next_action=next_action,
            next_action_due_date=next_action_due_date,
            notes=None,
        )
        due_note = (
            f" (due {values['next_action_due_date']})"
            if values["next_action_due_date"]
            else ""
        )
        return _persist_lead_update(
            db,
            current=current,
            values=values,
            event_type="crm_next_action",
            event_note=f"CRM next action set to: {values['next_action']}{due_note}.",
        )


def delete_lead(
    db: sqlite3.Connection,
    lead_id: int,
    *,
    confirmed: bool = False,
    actor: dict | sqlite3.Row | None = None,
    organization_id: int | None = None,
) -> sqlite3.Row:
    if confirmed is not True:
        raise ValueError("Lead deletion requires confirmation")
    safe_lead_id = _positive_id(lead_id, "Lead ID")
    safe_organization_id = _resolve_organization_id(db, organization_id)

    with _write_unit(db):
        lead = _require_lead(
            db,
            safe_lead_id,
            include_deleted=True,
            organization_id=safe_organization_id,
        )
        if actor is not None:
            from app.services.lead_research_permissions import (
                LeadPermissionError,
                can_soft_delete_lead,
            )
            from app.services.workspace_context import load_crm_actor_for_workspace
            try:
                effective_actor = load_crm_actor_for_workspace(
                    db, actor, safe_organization_id
                )
            except PermissionError as exc:
                raise LeadPermissionError(
                    "You are not allowed to archive this lead."
                ) from exc
            if not can_soft_delete_lead(effective_actor, lead):
                raise LeadPermissionError(
                    "You are not allowed to archive this lead."
                )
        if lead["deleted_at"] is not None:
            return lead
        cursor = db.execute(
            """
            UPDATE leads
            SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND deleted_at IS NULL
            """,
            (safe_lead_id, safe_organization_id),
        )
        if cursor.rowcount != 1:
            return _require_lead(
                db,
                safe_lead_id,
                include_deleted=True,
                organization_id=safe_organization_id,
            )
        db.execute(
            """
            UPDATE tasks
            SET status = 'abandoned', progress = 0, completed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (lead["quest_id"],),
        )
        _record_quest_update(
            db,
            quest_id=lead["quest_id"],
            event_type="crm_deleted",
            note=f"CRM lead soft-deleted: {lead['contact_person']} at {lead['company']}.",
            progress=0,
        )

    deleted = get_lead(
        db,
        safe_lead_id,
        include_deleted=True,
        organization_id=safe_organization_id,
    )
    if not deleted:
        raise RuntimeError("Deleted lead could not be reloaded")
    return deleted

def get_crm_dashboard_metrics(
    db: sqlite3.Connection,
    *,
    created_by_user_id: int | None = None,
    organization_id: int | None = None,
) -> dict[str, int]:
    safe_organization_id = _resolve_organization_id(db, organization_id)
    conditions = ["organization_id = ?", "deleted_at IS NULL"]
    parameters: list[object] = [safe_organization_id]

    if created_by_user_id is not None:
        conditions.append("created_by_user_id = ?")
        parameters.append(
            _positive_id(created_by_user_id, "Created-by user ID")
        )

    where = " AND ".join(conditions)

    row = db.execute(
        f"""
        SELECT
            COUNT(*) AS total_leads,
            SUM(CASE WHEN priority = 'high' THEN 1 ELSE 0 END)
                AS high_priority_leads,
            SUM(CASE WHEN pipeline_status = 'contacted' THEN 1 ELSE 0 END)
                AS contacted,
            SUM(CASE WHEN pipeline_status = 'replied' THEN 1 ELSE 0 END)
                AS replies,
            SUM(CASE WHEN pipeline_status = 'meeting' THEN 1 ELSE 0 END)
                AS meetings,
            SUM(CASE WHEN pipeline_status = 'proposal' THEN 1 ELSE 0 END)
                AS proposals,
            SUM(CASE WHEN pipeline_status = 'won' THEN 1 ELSE 0 END)
                AS won_clients
        FROM leads
        WHERE {where}
        """,
        parameters,
    ).fetchone()

    metric_names = (
        "total_leads",
        "high_priority_leads",
        "contacted",
        "replies",
        "meetings",
        "proposals",
        "won_clients",
    )
    return {name: int(row[name] or 0) for name in metric_names}
