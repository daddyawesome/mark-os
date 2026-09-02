from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from dataclasses import dataclass

from app.services.leads import (
    create_lead,
    find_active_lead_by_dedupe_key,
    normalize_lead_field_values,
)
from app.services.team_users import list_active_lead_sourcers


MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 500
LEAD_CSV_TEMPLATE_FILENAME = "mark_os_lead_import_template.csv"

CSV_HEADERS = (
    "Company",
    "Contact person",
    "Job title",
    "Source",
    "Source link",
    "Problem or opportunity",
    "Why Mark fits",
    "Pipeline status",
    "Priority",
    "Next action",
    "Due date",
    "Notes",
)

_HEADER_TO_FIELD = {
    "Company": "company",
    "Contact person": "contact_person",
    "Job title": "job_title",
    "Source": "source",
    "Source link": "source_url",
    "Problem or opportunity": "problem_opportunity",
    "Why Mark fits": "why_mark_fits",
    "Pipeline status": "pipeline_status",
    "Priority": "priority",
    "Next action": "next_action",
    "Due date": "next_action_due_date",
    "Notes": "notes",
}


class LeadCsvImportError(ValueError):
    """Raised when the CSV file itself cannot be safely imported."""


@dataclass(frozen=True)
class LeadCsvRowError:
    row_number: int
    message: str


@dataclass(frozen=True)
class LeadCsvImportResult:
    total_rows: int
    created_count: int
    duplicate_count: int
    invalid_count: int
    errors: tuple[LeadCsvRowError, ...]
    skipped_count: int = 0


@dataclass(frozen=True)
class LeadCsvPreviewRow:
    row_number: int
    company: str
    contact_person: str
    source: str
    pipeline_status: str
    priority: str
    status: str
    message: str | None = None
    duplicate_lead_id: int | None = None
    duplicate_row_number: int | None = None


@dataclass(frozen=True)
class LeadCsvPreviewResult:
    file_digest: str
    total_rows: int
    valid_count: int
    invalid_count: int
    duplicate_count: int
    rows: tuple[LeadCsvPreviewRow, ...]


def _normalized_header(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def lead_csv_template_bytes() -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(CSV_HEADERS)
    return stream.getvalue().encode("utf-8-sig")


def _decode_csv(content: bytes) -> str:
    if not isinstance(content, bytes):
        raise LeadCsvImportError("The uploaded CSV must be read as bytes.")
    if not content:
        raise LeadCsvImportError("The uploaded CSV is empty.")
    if len(content) > MAX_CSV_BYTES:
        raise LeadCsvImportError(
            f"The CSV is too large. The maximum size is {MAX_CSV_BYTES // 1_000_000} MB."
        )
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LeadCsvImportError("The CSV must use UTF-8 encoding.") from exc


def _resolve_headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise LeadCsvImportError("The CSV does not contain a header row.")

    normalized_to_original: dict[str, str] = {}
    for raw_header in fieldnames:
        if raw_header is None:
            continue
        clean_header = raw_header.strip()
        normalized = _normalized_header(clean_header)
        if not normalized:
            raise LeadCsvImportError("The CSV contains a blank column name.")
        if normalized in normalized_to_original:
            raise LeadCsvImportError(
                f'The CSV contains the duplicate column "{clean_header}".'
            )
        normalized_to_original[normalized] = raw_header

    missing = [
        header
        for header in CSV_HEADERS
        if _normalized_header(header) not in normalized_to_original
    ]
    if missing:
        raise LeadCsvImportError(
            "The CSV is missing required columns: " + ", ".join(missing)
        )

    return {
        header: normalized_to_original[_normalized_header(header)]
        for header in CSV_HEADERS
    }


def _read_rows(content: bytes) -> tuple[list[tuple[int, dict[str, str]]], str]:
    text = _decode_csv(content)
    stream = io.StringIO(text, newline="")

    try:
        reader = csv.DictReader(stream)
        header_lookup = _resolve_headers(reader.fieldnames)
        rows: list[tuple[int, dict[str, str]]] = []

        for row_number, source_row in enumerate(reader, start=2):
            if source_row is None:
                continue

            values = {
                target_field: (source_row.get(source_header) or "").strip()
                for csv_header, target_field in _HEADER_TO_FIELD.items()
                for source_header in (header_lookup[csv_header],)
            }

            if not any(values.values()):
                continue

            rows.append((row_number, values))
            if len(rows) > MAX_CSV_ROWS:
                raise LeadCsvImportError(
                    f"The CSV contains more than the {MAX_CSV_ROWS}-lead limit."
                )
    except csv.Error as exc:
        raise LeadCsvImportError(f"The CSV could not be parsed: {exc}") from exc

    if not rows:
        raise LeadCsvImportError("The CSV does not contain any lead rows.")

    file_digest = hashlib.sha256(content).hexdigest()
    return rows, file_digest


def preview_leads_from_csv(
    db: sqlite3.Connection,
    content: bytes,
    *,
    pipeline_status_override: str | None = None,
    organization_id: int | None = None,
) -> LeadCsvPreviewResult:
    """Parse and validate CSV rows without writing leads or quests."""
    rows, file_digest = _read_rows(content)
    preview_rows: list[LeadCsvPreviewRow] = []
    seen_dedupe_keys: dict[str, int] = {}
    valid_count = 0
    invalid_count = 0
    duplicate_count = 0

    for row_number, values in rows:
        try:
            normalized = normalize_lead_field_values(
                company=values["company"],
                contact_person=values["contact_person"],
                job_title=values["job_title"],
                source=values["source"],
                source_url=values["source_url"],
                problem_opportunity=values["problem_opportunity"],
                why_mark_fits=values["why_mark_fits"],
                pipeline_status=(
                    pipeline_status_override
                    or values["pipeline_status"]
                    or "new"
                ),
                priority=values["priority"] or "medium",
                next_action=values["next_action"],
                next_action_due_date=values["next_action_due_date"] or None,
                notes=values["notes"],
            )
        except ValueError as exc:
            invalid_count += 1
            preview_rows.append(
                LeadCsvPreviewRow(
                    row_number=row_number,
                    company=values["company"],
                    contact_person=values["contact_person"],
                    source=values["source"],
                    pipeline_status=values["pipeline_status"] or "new",
                    priority=values["priority"] or "medium",
                    status="invalid",
                    message=str(exc),
                )
            )
            continue

        dedupe_key = str(normalized["dedupe_key"])
        duplicate_in_file = seen_dedupe_keys.get(dedupe_key)
        if duplicate_in_file is not None:
            duplicate_count += 1
            preview_rows.append(
                LeadCsvPreviewRow(
                    row_number=row_number,
                    company=str(normalized["company"]),
                    contact_person=str(normalized["contact_person"]),
                    source=str(normalized["source"]),
                    pipeline_status=str(normalized["pipeline_status"]),
                    priority=str(normalized["priority"]),
                    status="duplicate_in_file",
                    message=(
                        f"Duplicate of CSV row {duplicate_in_file} "
                        f"({normalized['company']})."
                    ),
                    duplicate_row_number=duplicate_in_file,
                )
            )
            continue

        existing = find_active_lead_by_dedupe_key(
            db,
            dedupe_key,
            organization_id=organization_id,
        )
        if existing is not None:
            duplicate_count += 1
            preview_rows.append(
                LeadCsvPreviewRow(
                    row_number=row_number,
                    company=str(normalized["company"]),
                    contact_person=str(normalized["contact_person"]),
                    source=str(normalized["source"]),
                    pipeline_status=str(normalized["pipeline_status"]),
                    priority=str(normalized["priority"]),
                    status="duplicate_existing",
                    message=(
                        f"Matches existing lead #{existing['id']} "
                        f"({existing['company']})."
                    ),
                    duplicate_lead_id=int(existing["id"]),
                )
            )
            continue

        seen_dedupe_keys[dedupe_key] = row_number
        valid_count += 1
        preview_rows.append(
            LeadCsvPreviewRow(
                row_number=row_number,
                company=str(normalized["company"]),
                contact_person=str(normalized["contact_person"]),
                source=str(normalized["source"]),
                pipeline_status=str(normalized["pipeline_status"]),
                priority=str(normalized["priority"]),
                status="valid",
            )
        )

    return LeadCsvPreviewResult(
        file_digest=file_digest,
        total_rows=len(rows),
        valid_count=valid_count,
        invalid_count=invalid_count,
        duplicate_count=duplicate_count,
        rows=tuple(preview_rows),
    )


def import_leads_from_csv(
    db: sqlite3.Connection,
    content: bytes,
    *,
    pipeline_status_override: str | None = None,
    created_by_user_id: int | None = None,
    assigned_to_user_id: int | None = None,
    business_development_owner_user_id: int | None = None,
    organization_id: int | None = None,
    selected_row_numbers: frozenset[int] | None = None,
    researcher_user_id: int | None = None,
) -> LeadCsvImportResult:
    """Import valid rows while reporting duplicates and row-level errors.

    Every valid row goes through the existing create_lead service. This keeps
    CRM duplicate handling, linked-quest creation, pipeline synchronization,
    and zero-XP behavior identical to manual lead creation. A role-aware route
    may force all imported rows to a safe review status.

    ``selected_row_numbers``, when given, restricts the import to that subset
    of previewed CSV rows; every other row is reported as skipped rather than
    imported. ``researcher_user_id`` bulk-assigns the imported rows to one
    active Lead Sourcer in the workspace instead of the default assignee,
    which grants that sourcer visibility through the same ``assigned_to``
    matching CRM permissions already use elsewhere.
    """
    rows, file_digest = _read_rows(content)

    effective_assigned_to_user_id = assigned_to_user_id
    if researcher_user_id is not None:
        if organization_id is None:
            raise LeadCsvImportError(
                "Researcher assignment requires a workspace context."
            )
        sourcers = list_active_lead_sourcers(
            db,
            organization_id=organization_id,
        )
        if not any(
            sourcer["id"] == researcher_user_id for sourcer in sourcers
        ):
            raise LeadCsvImportError(
                "Researcher must be an active Lead Sourcer in this "
                "workspace."
            )
        effective_assigned_to_user_id = researcher_user_id

    created_count = 0
    duplicate_count = 0
    skipped_count = 0
    errors: list[LeadCsvRowError] = []

    for row_number, values in rows:
        if (
            selected_row_numbers is not None
            and row_number not in selected_row_numbers
        ):
            skipped_count += 1
            continue

        request_key = f"csv:{file_digest[:40]}:{row_number}"
        try:
            result = create_lead(
                db,
                company=values["company"],
                contact_person=values["contact_person"],
                job_title=values["job_title"],
                source=values["source"],
                source_url=values["source_url"],
                problem_opportunity=values["problem_opportunity"],
                why_mark_fits=values["why_mark_fits"],
                pipeline_status=(
                    pipeline_status_override
                    or values["pipeline_status"]
                    or "new"
                ),
                priority=values["priority"] or "medium",
                next_action=values["next_action"],
                next_action_due_date=values["next_action_due_date"] or None,
                notes=values["notes"],
                request_key=request_key,
                created_by_user_id=created_by_user_id,
                assigned_to_user_id=effective_assigned_to_user_id,
                business_development_owner_user_id=(
                    business_development_owner_user_id
                ),
                organization_id=organization_id,
            )
        except ValueError as exc:
            errors.append(
                LeadCsvRowError(
                    row_number=row_number,
                    message=str(exc),
                )
            )
            continue

        if result.created:
            created_count += 1
        else:
            duplicate_count += 1

    return LeadCsvImportResult(
        total_rows=len(rows),
        created_count=created_count,
        duplicate_count=duplicate_count,
        invalid_count=len(errors),
        errors=tuple(errors),
        skipped_count=skipped_count,
    )
