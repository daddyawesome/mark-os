from __future__ import annotations

import hashlib
import secrets
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.access_control import has_crm_owner_authority
from app.services.leads import LeadCreateResult, create_lead
from app.services.team_users import get_primary_owner_id


Record = Mapping[str, Any] | sqlite3.Row

TOKEN_BYTES = 32
MAX_SOURCE_NAME_LENGTH = 100
MAX_EXTERNAL_ID_LENGTH = 200
MAX_PAYLOAD_TEXT_LENGTH = 4_000

DEFAULT_WHY_MARK_FITS = (
    "Not yet assessed. This lead arrived through an automated webhook and "
    "is pending human research."
)
DEFAULT_NEXT_ACTION = "Review this inbound webhook lead and begin research."


class WebhookIntakeError(ValueError):
    """Raised when a webhook payload cannot be safely accepted."""


class WebhookAuthenticationError(PermissionError):
    """Raised when a webhook token is missing, invalid, or revoked."""


@dataclass(frozen=True)
class WebhookTokenIssued:
    id: int
    organization_id: int
    source_name: str
    token: str
    token_last_four: str


@dataclass(frozen=True)
class IntakeResult:
    outcome: str
    lead_id: int | None
    created: bool


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _required_text(value: Any, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise WebhookIntakeError(f"{field_name} must be text.")
    clean = " ".join(value.strip().split())
    if not clean:
        raise WebhookIntakeError(f"{field_name} is required.")
    if len(clean) > maximum:
        raise WebhookIntakeError(
            f"{field_name} must be {maximum} characters or fewer."
        )
    return clean


def _optional_text(value: Any, field_name: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WebhookIntakeError(f"{field_name} must be text.")
    clean = " ".join(value.strip().split())
    if len(clean) > maximum:
        raise WebhookIntakeError(
            f"{field_name} must be {maximum} characters or fewer."
        )
    return clean


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_webhook_token(
    db: sqlite3.Connection,
    *,
    actor: Record,
    organization_id: int,
    source_name: str,
) -> WebhookTokenIssued:
    """Issue a new webhook intake token; the raw value is returned only once."""
    if not has_crm_owner_authority(actor):
        raise PermissionError(
            "Only Mark or workspace-owner authority can issue webhook tokens."
        )
    safe_organization_id = _positive_id(organization_id, "Organization ID")
    clean_source_name = _required_text(
        source_name,
        "Source name",
        MAX_SOURCE_NAME_LENGTH,
    )

    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    token_hash = _hash_token(raw_token)
    actor_id = actor.get("id") if hasattr(actor, "get") else None

    cursor = db.execute(
        """
        INSERT INTO webhook_intake_tokens (
            organization_id, source_name, token_hash, token_last_four,
            created_by_user_id
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            safe_organization_id,
            clean_source_name,
            token_hash,
            raw_token[-4:],
            int(actor_id) if actor_id else None,
        ),
    )
    return WebhookTokenIssued(
        id=cursor.lastrowid,
        organization_id=safe_organization_id,
        source_name=clean_source_name,
        token=raw_token,
        token_last_four=raw_token[-4:],
    )


def list_webhook_tokens(
    db: sqlite3.Connection,
    *,
    organization_id: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT id, organization_id, source_name, token_last_four, active,
               created_by_user_id, created_at, revoked_at, revoked_by_user_id,
               last_used_at
        FROM webhook_intake_tokens
        WHERE organization_id = ?
        ORDER BY active DESC, created_at DESC
        """,
        (_positive_id(organization_id, "Organization ID"),),
    ).fetchall()
    return [dict(row) for row in rows]


def revoke_webhook_token(
    db: sqlite3.Connection,
    token_id: int,
    *,
    actor: Record,
    organization_id: int,
) -> None:
    if not has_crm_owner_authority(actor):
        raise PermissionError(
            "Only Mark or workspace-owner authority can revoke webhook tokens."
        )
    actor_id = actor.get("id") if hasattr(actor, "get") else None
    cursor = db.execute(
        """
        UPDATE webhook_intake_tokens
        SET active = 0,
            revoked_at = CURRENT_TIMESTAMP,
            revoked_by_user_id = ?
        WHERE id = ? AND organization_id = ? AND active = 1
        """,
        (
            int(actor_id) if actor_id else None,
            _positive_id(token_id, "Token ID"),
            _positive_id(organization_id, "Organization ID"),
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("Active token not found.")


def authenticate_webhook_token(
    db: sqlite3.Connection,
    raw_token: str,
) -> dict[str, Any]:
    """Look up and validate a bearer token; never distinguishes missing vs.

    revoked in the error message so a caller cannot enumerate token state.
    """
    clean_token = (raw_token or "").strip()
    if not clean_token:
        raise WebhookAuthenticationError("A webhook token is required.")

    token_hash = _hash_token(clean_token)
    row = db.execute(
        """
        SELECT *
        FROM webhook_intake_tokens
        WHERE token_hash = ? AND active = 1
        """,
        (token_hash,),
    ).fetchone()
    if row is None:
        raise WebhookAuthenticationError("Invalid or revoked webhook token.")

    db.execute(
        "UPDATE webhook_intake_tokens SET last_used_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (int(row["id"]),),
    )
    return dict(row)


def _record_event(
    db: sqlite3.Connection,
    *,
    token_id: int,
    organization_id: int,
    external_id: str,
    outcome: str,
    lead_id: int | None,
    error_summary: str = "",
) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO webhook_intake_events (
            token_id, organization_id, external_id, outcome, lead_id,
            error_summary
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            token_id,
            organization_id,
            external_id,
            outcome,
            lead_id,
            error_summary[:500],
        ),
    )


def ingest_lead_payload(
    db: sqlite3.Connection,
    *,
    token_record: Record,
    payload: Mapping[str, Any],
) -> IntakeResult:
    """Create a lead from a validated webhook payload, idempotent per source.

    Reuses the exact same ``create_lead`` service every manual and CSV-import
    lead already goes through, so duplicate detection, quest linking, and the
    draft research pipeline stay identical. Nothing here can approve
    research, outreach, pipeline movement, or any financial action — the
    created lead starts at the same ``draft``/``new`` state every other lead
    starts at.
    """
    organization_id = int(token_record["organization_id"])
    token_id = int(token_record["id"])

    if not isinstance(payload, Mapping):
        raise WebhookIntakeError("Payload must be a JSON object.")

    external_id = _required_text(
        payload.get("external_id"),
        "external_id",
        MAX_EXTERNAL_ID_LENGTH,
    )

    existing_event = db.execute(
        """
        SELECT outcome, lead_id
        FROM webhook_intake_events
        WHERE token_id = ? AND external_id = ?
        """,
        (token_id, external_id),
    ).fetchone()
    if existing_event is not None:
        return IntakeResult(
            outcome=str(existing_event["outcome"]),
            lead_id=(
                int(existing_event["lead_id"])
                if existing_event["lead_id"] is not None
                else None
            ),
            created=False,
        )

    try:
        company = _required_text(
            payload.get("company"),
            "company",
            200,
        )
        contact_person = _required_text(
            payload.get("contact_person"),
            "contact_person",
            200,
        )
        job_title = _optional_text(payload.get("job_title"), "job_title", 200)
        source_url = _optional_text(
            payload.get("source_url"),
            "source_url",
            2_000,
        )
        problem_opportunity = _required_text(
            payload.get("message") or payload.get("problem_opportunity"),
            "message",
            MAX_PAYLOAD_TEXT_LENGTH,
        )
        why_mark_fits = _optional_text(
            payload.get("why_mark_fits"),
            "why_mark_fits",
            MAX_PAYLOAD_TEXT_LENGTH,
        ) or DEFAULT_WHY_MARK_FITS
        next_action = _optional_text(
            payload.get("next_action"),
            "next_action",
            500,
        ) or DEFAULT_NEXT_ACTION
        notes = _optional_text(payload.get("notes"), "notes", 5_000)

        owner_id = get_primary_owner_id(db, active_only=True)
        request_key = f"webhook:{token_id}:{external_id}"

        result: LeadCreateResult = create_lead(
            db,
            company=company,
            contact_person=contact_person,
            job_title=job_title,
            source=str(token_record["source_name"]),
            source_url=source_url,
            problem_opportunity=problem_opportunity,
            why_mark_fits=why_mark_fits,
            pipeline_status="new",
            next_action=next_action,
            notes=notes,
            request_key=request_key,
            assigned_to_user_id=owner_id,
            organization_id=organization_id,
        )
    except (WebhookIntakeError, ValueError) as exc:
        _record_event(
            db,
            token_id=token_id,
            organization_id=organization_id,
            external_id=external_id,
            outcome="rejected",
            lead_id=None,
            error_summary=str(exc),
        )
        raise WebhookIntakeError(str(exc)) from exc

    outcome = "created" if result.created else "duplicate"
    _record_event(
        db,
        token_id=token_id,
        organization_id=organization_id,
        external_id=external_id,
        outcome=outcome,
        lead_id=int(result.lead["id"]),
    )
    return IntakeResult(
        outcome=outcome,
        lead_id=int(result.lead["id"]),
        created=result.created,
    )
