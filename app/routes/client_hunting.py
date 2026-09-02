from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from app.database import get_db
from app.db.lead_activities import (
    ACTIVITY_TYPES,
    CHANNELS,
    RESPONSE_STATUSES,
)
from app.services.lead_activities import (
    LEAD_SOURCER_ACTIVITY_TYPES,
    LeadActivityNotFoundError,
    LeadActivityPermissionError,
    correct_activity as correct_activity_record,
    create_activity as create_activity_record,
    get_activity as get_activity_record,
    list_active_activity_users,
    list_lead_activities,
    soft_delete_activity as soft_delete_activity_record,
)
from app.routes.shared import load_system_state, templates
from app.services.lead_csv_import import (
    CSV_HEADERS,
    LEAD_CSV_TEMPLATE_FILENAME,
    MAX_CSV_BYTES,
    MAX_CSV_ROWS,
    LeadCsvImportError,
    import_leads_from_csv,
    lead_csv_template_bytes,
    preview_leads_from_csv,
)
from app.services.access_control import (
    has_crm_owner_authority,
    is_lead_sourcer,
    is_owner,
    is_relationship_manager,
)
from app.services.lead_research_permissions import (
    LeadPermissionError,
    can_approve_outreach,
    can_edit_research,
    can_perform_delegated_contact,
    can_view_lead,
)
from app.services.lead_qualification_permissions import (
    can_decide_qualification,
    can_edit_qualification,
)
from app.services.client_delivery import get_client_by_lead
from app.services.client_delivery_permissions import can_manage_clients
from app.services.lead_pipeline_workflow import (
    CONTACT_ACTIVITY_TYPES,
    CONTACT_CHANNELS,
    CONTACT_RESPONSE_STATUSES,
    LeadPipelineRuleError,
    change_pipeline_stage,
    update_owner_lead,
)
from app.services.lead_work_queues import (
    build_role_aware_crm_dashboard,
)
from app.services.follow_up_command_center import (
    FollowUpFilterError,
    FollowUpPermissionError,
    build_follow_up_command_center,
)
from app.services.team_users import (
    get_primary_owner_id,
    list_active_lead_sourcers,
)
from app.services.workspace_context import require_request_organization_id
from app.services.relationship_manager import (
    assign_relationship_manager,
    can_update_relationship_next_action,
    list_active_relationship_managers,
    update_next_action_for_actor,
)
from app.services.leads import (
    PIPELINE_STATUSES,
    PRIORITIES,
    LeadEditConflictError,
    create_lead as create_lead_record,
    delete_lead as delete_lead_record,
    get_crm_dashboard_metrics,
    get_lead,
)
from app.services.lead_export import export_leads_csv, export_leads_json

router = APIRouter(prefix="/crm")
PIPELINE_LABELS = {
    "new": "New",
    "reviewed": "Reviewed",
    "contacted": "Contacted",
    "replied": "Replied",
    "meeting": "Meeting",
    "proposal": "Proposal",
    "won": "Won",
    "lost": "Lost",
}
PRIORITY_LABELS = {"high": "High", "medium": "Medium", "low": "Low"}
PIPELINE_OPTIONS = tuple(
    (status, PIPELINE_LABELS[status]) for status in PIPELINE_STATUSES
)
PRIORITY_OPTIONS = tuple(
    (priority, PRIORITY_LABELS[priority]) for priority in PRIORITIES
)
NOTICE_MESSAGES = {
    "created": "Lead and linked quest created.",
    "duplicate": "That request was already saved. The existing lead is shown below.",
    "updated": "Lead details updated.",
    "research_submitted": "Research submitted for workspace-owner review.",
    "pipeline": "Pipeline status updated.",
    "next_action": "Next action updated.",
    "deleted": "Lead archived. Its quest history was preserved.",
    "research_approved": 'Lead research approved.',
    "research_changes_requested": 'Changes requested. The Lead Researcher can edit and resubmit.',
    "research_rejected": 'Lead research rejected.',
    "outreach_approved": "Outreach approved. This lead may now move to Contacted.",
    "relationship_owner": "Business development owner updated.",
    "activity_created": "Lead activity recorded.",
    "activity_corrected": "Lead activity corrected with an audit reason.",
    "activity_deleted": "Lead activity soft deleted with an audit reason.",
    "research_bulk_submitted": "Selected research submitted for workspace-owner review.",
    "research_bulk_partial": "Some selected leads were submitted; others could not be and were left untouched.",
    "research_bulk_failed": "None of the selected leads could be submitted. They were left untouched.",
    "qualification_updated": "Qualification notes saved.",
    "qualification_decided": "Qualification decision recorded.",
}
ERROR_MESSAGES = {
    "invalid": "The lead could not be saved. Check the required fields and allowed values.",
    "confirmation": 'Type DELETE exactly to archive this lead.',
    "forbidden": "That action requires workspace-owner CRM authority or global Owner access.",
    "review_notes_required": 'Review notes are required when requesting changes or rejecting.',
    "invalid_review": 'The research review decision could not be saved.',
    "pipeline_rule": "That pipeline move is not allowed. Contacted requires approved research, outreach approval, and a complete contact audit; Proposal requires Meeting; Won requires Proposal.",
    "stale": "This lead changed in another session. Reload the latest version and try again.",
    "research_bulk_empty": "Select at least one lead to submit for review.",
}
METRIC_DEFINITIONS = (
    ("Total leads", "total_leads"),
    ("High-priority leads", "high_priority_leads"),
    ("Contacted", "contacted"),
    ("Replies", "replies"),
    ("Meetings", "meetings"),
    ("Proposals", "proposals"),
    ("Won clients", "won_clients"),
)


def _message(mapping: dict[str, str], key: str | None) -> str | None:
    """Resolve only known message keys so query strings cannot inject copy."""
    return mapping.get(key or "")


def _optional_form_text(value: object) -> str:
    """Normalize submitted strings and FastAPI direct-call defaults."""
    return value.strip() if isinstance(value, str) else ""


def _optional_form_text(value: object) -> str:
    """Normalize submitted strings and FastAPI direct-call defaults."""
    return value.strip() if isinstance(value, str) else ""


def _optional_positive_form_id(
    value: object,
    field_name: str,
) -> int | None:
    clean = _optional_form_text(value)
    if not clean:
        return None
    try:
        parsed = int(clean)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a positive integer."
        ) from exc
    if parsed <= 0:
        raise ValueError(
            f"{field_name} must be a positive integer."
        )
    return parsed

def _expected_row_version(value: object) -> int | None:
    """Require HTTP form versions while tolerating legacy direct route calls."""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        # Direct unit tests invoke route functions without FastAPI dependency
        # injection, leaving the Form() object in place. Runtime HTTP requests
        # never receive that object.
        return None
    clean = str(value).strip()
    if not clean:
        raise ValueError("Lead row version is required")
    try:
        parsed = int(clean)
    except ValueError as exc:
        raise ValueError("Lead row version must be an integer") from exc
    if parsed <= 0:
        raise ValueError("Lead row version must be positive")
    return parsed


def _request_organization_id(
    db,
    request: Request,
) -> int:
    try:
        return require_request_organization_id(
            request,
            db=db,
        )
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=403,
            detail="An authorized CRM workspace is required",
        ) from exc


def _activity_form_context(
    db,
    user,
    *,
    organization_id: int,
    lead=None,
) -> dict:
    can_contact_this_lead = can_perform_delegated_contact(user, lead)
    can_create = (
        has_crm_owner_authority(user)
        or is_lead_sourcer(user)
        or can_contact_this_lead
    )
    activity_types = (
        ACTIVITY_TYPES
        if has_crm_owner_authority(user)
        else tuple(
            activity_type
            for activity_type in ACTIVITY_TYPES
            if activity_type in LEAD_SOURCER_ACTIVITY_TYPES
        )
        if is_lead_sourcer(user)
        else CONTACT_ACTIVITY_TYPES
        if can_contact_this_lead
        else ()
    )
    channels = (
        CHANNELS
        if has_crm_owner_authority(user)
        else CONTACT_CHANNELS
        if can_contact_this_lead
        else ("internal",)
    )
    can_use_contact_form = has_crm_owner_authority(user) or can_contact_this_lead
    return {
        "can_create_activity": can_create,
        "can_contact_this_lead": can_contact_this_lead,
        "activity_type_options": activity_types,
        "activity_channel_options": channels,
        "activity_response_status_options": RESPONSE_STATUSES,
        "contact_activity_type_options": (
            CONTACT_ACTIVITY_TYPES if can_use_contact_form else ()
        ),
        "contact_channel_options": (
            CONTACT_CHANNELS if can_use_contact_form else ()
        ),
        "contact_response_status_options": (
            CONTACT_RESPONSE_STATUSES if can_use_contact_form else ()
        ),
        "activity_users": (
            list_active_activity_users(
                db,
                actor=user,
                organization_id=organization_id,
            )
            if can_create
            else []
        ),
    }

def _can_correct_activity_in_ui(
    user,
    activity: dict,
) -> bool:
    if has_crm_owner_authority(user):
        return True
    return (
        is_lead_sourcer(user)
        and int(activity["created_by_user_id"])
        == int(user["id"])
        and str(activity["activity_type"])
        in LEAD_SOURCER_ACTIVITY_TYPES
    )


def _activity_redirect(
    lead_id: int,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    key = "notice" if notice else "error"
    value = notice or error or "activity_invalid"
    return RedirectResponse(
        url=(
            f"/crm/leads/{lead_id}?{key}={value}"
            "#lead-activity-timeline"
        ),
        status_code=303,
    )


def _activity_for_lead_or_404(
    db,
    *,
    lead_id: int,
    activity_id: int,
    user,
    organization_id: int,
):
    try:
        activity = get_activity_record(
            db,
            activity_id,
            actor=user,
            organization_id=organization_id,
        )
    except LeadActivityNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Lead activity not found",
        ) from exc
    if int(activity["lead_id"]) != int(lead_id):
        raise HTTPException(
            status_code=404,
            detail="Lead activity not found",
        )
    return activity


def _lead_or_404(
    db,
    lead_id: int,
    request: Request,
):
    organization_id = _request_organization_id(db, request)
    lead = get_lead(
        db,
        lead_id,
        organization_id=organization_id,
    )
    if lead is None or not can_view_lead(
        request.state.current_user,
        lead,
    ):
        # Do not reveal whether another workspace or user's lead exists.
        raise HTTPException(
            status_code=404,
            detail="Lead not found",
        )
    return lead


def _shared_context(db, request: Request) -> dict:
    user = request.state.current_user
    global_owner = is_owner(user)
    return {
        "pipeline_options": PIPELINE_OPTIONS,
        "priority_options": PRIORITY_OPTIONS,
        "system_state": load_system_state(db) if global_owner else None,
        "current_user": user,
        "can_manage_crm": has_crm_owner_authority(user),
        "can_view_linked_quest": global_owner,
        "is_global_owner": global_owner,
    }


def _add_leads_context(
    db,
    request: Request,
    *,
    import_result=None,
    import_preview=None,
    import_error: str | None = None,
    csv_content_b64: str | None = None,
) -> dict:
    shared = _shared_context(db, request)
    active_lead_sourcers: list[dict] = []
    active_relationship_managers: list[dict] = []
    if shared["can_manage_crm"]:
        organization_id = _request_organization_id(db, request)
        active_lead_sourcers = list_active_lead_sourcers(
            db,
            organization_id=organization_id,
        )
        active_relationship_managers = list_active_relationship_managers(
            db,
            organization_id=organization_id,
        )
    return {
        "request_key": uuid4().hex,
        "notice": _message(NOTICE_MESSAGES, request.query_params.get("notice")),
        "error": _message(ERROR_MESSAGES, request.query_params.get("error")),
        "import_result": import_result,
        "import_preview": import_preview,
        "import_error": import_error,
        "csv_content_b64": csv_content_b64,
        "active_lead_sourcers": active_lead_sourcers,
        "active_relationship_managers": active_relationship_managers,
        "csv_headers": CSV_HEADERS,
        "max_csv_rows": MAX_CSV_ROWS,
        "max_csv_size_mb": MAX_CSV_BYTES // 1_000_000,
        **shared,
    }


@router.get("", response_class=HTMLResponse)
def crm_dashboard(request: Request):
    user = request.state.current_user

    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        dashboard = build_role_aware_crm_dashboard(
            db,
            user,
            organization_id=organization_id,
        )
        metric_cards = dashboard["metric_cards"]

        if is_owner(user):
            metrics = get_crm_dashboard_metrics(
                db,
                organization_id=organization_id,
            )
            metric_cards = [
                {
                    "label": label,
                    "value": metrics[key],
                }
                for label, key in METRIC_DEFINITIONS
            ]

        context = {
            "leads": dashboard["leads"],
            "metric_cards": metric_cards,
            "queue_cards": dashboard[
                "queue_cards"
            ],
            "queue_mode": dashboard[
                "queue_mode"
            ],
            "notice": _message(
                NOTICE_MESSAGES,
                request.query_params.get("notice"),
            ),
            "error": _message(
                ERROR_MESSAGES,
                request.query_params.get("error"),
            ),
            **_shared_context(db, request),
        }

    return templates.TemplateResponse(
        request=request,
        name="client_hunting.html",
        context=context,
    )

@router.get("/follow-ups", response_class=HTMLResponse)
def follow_up_command_center_page(
    request: Request,
    assignee_id: int | None = None,
    researcher_id: int | None = None,
    business_development_owner_id: int | None = None,
):
    user = request.state.current_user
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            command_center = build_follow_up_command_center(
                db,
                user,
                organization_id=organization_id,
                assignee_id=assignee_id,
                researcher_id=researcher_id,
                business_development_owner_id=(
                    business_development_owner_id
                ),
            )
        except FollowUpPermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail="CRM access is required",
            ) from exc
        except FollowUpFilterError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        selected = command_center["selected_filters"]
        context = {
            "command_center": command_center,
            "has_active_filters": any(
                value is not None
                for value in selected.values()
            ),
            **_shared_context(db, request),
        }

    return templates.TemplateResponse(
        request=request,
        name="follow_up_command_center.html",
        context=context,
    )
@router.get("/leads/new", response_class=HTMLResponse)
def new_lead_page(request: Request):
    with get_db() as db:
        _request_organization_id(db, request)
        context = _add_leads_context(db, request)
    return templates.TemplateResponse(
        request=request,
        name="add_leads.html",
        context=context,
    )


@router.get("/leads/export")
def export_leads(
    request: Request,
    format: str = "csv",
    scope: str = "visible",
):
    normalized_format = (format or "csv").strip().casefold()
    if normalized_format not in {"csv", "json"}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported export format.",
        )
    approved_only = (scope or "visible").strip().casefold() == "approved"

    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        if normalized_format == "csv":
            content = export_leads_csv(
                db,
                request.state.current_user,
                organization_id=organization_id,
                approved_only=approved_only,
            )
            media_type = "text/csv; charset=utf-8"
        else:
            content = export_leads_json(
                db,
                request.state.current_user,
                organization_id=organization_id,
                approved_only=approved_only,
            )
            media_type = "application/json"

    filename_scope = "approved-leads" if approved_only else "leads"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                "attachment; filename="
                f'"mark_os_{filename_scope}_export.{normalized_format}"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/backup/download")
def download_crm_backup(request: Request):
    """Create and stream a fresh, verified SQLite backup to the Owner.

    Restricted to the global Owner: the backup covers the entire MARK-OS
    database, including every organization workspace, so it must never be
    reachable by workspace-scoped CRM or Pendang authority.
    """
    if not is_owner(request.state.current_user):
        raise HTTPException(status_code=404, detail="Not found")

    from app import database
    from app.services.database_backup import create_sqlite_backup

    source = Path(database.DB_PATH).expanduser().resolve()
    destination = Path(
        os.getenv("MARK_OS_BACKUP_DIR", "")
        or source.parent / "backups"
    ).expanduser().resolve()
    prefix = os.getenv("MARK_OS_BACKUP_PREFIX", "mark_os")

    try:
        result = create_sqlite_backup(
            source_path=source,
            backup_directory=destination,
            backup_prefix=prefix,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="The backup could not be created.",
        ) from exc

    backup_path = Path(result.backup_path)
    return FileResponse(
        backup_path,
        media_type="application/x-sqlite3",
        filename=backup_path.name,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/leads/import/template")
def download_lead_csv_template(request: Request):
    with get_db() as db:
        _request_organization_id(db, request)
    return Response(
        content=lead_csv_template_bytes(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{LEAD_CSV_TEMPLATE_FILENAME}"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/leads/import/preview", response_class=HTMLResponse)
async def preview_leads_csv(
    request: Request,
    csv_file: UploadFile = File(...),
):
    filename = (csv_file.filename or "").strip()
    content = b""
    import_error: str | None = None
    import_preview = None

    try:
        if not filename.lower().endswith(".csv"):
            raise LeadCsvImportError("Choose a file with a .csv extension.")

        content = await csv_file.read(MAX_CSV_BYTES + 1)
        if len(content) > MAX_CSV_BYTES:
            raise LeadCsvImportError(
                f"The CSV is too large. The maximum size is "
                f"{MAX_CSV_BYTES // 1_000_000} MB."
            )
    except LeadCsvImportError as exc:
        import_error = str(exc)
    finally:
        await csv_file.close()

    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        if import_error is None:
            try:
                import_preview = preview_leads_from_csv(
                    db,
                    content,
                    organization_id=organization_id,
                    pipeline_status_override=(
                        "new"
                        if (
                            is_lead_sourcer(request.state.current_user)
                            or (
                                is_relationship_manager(
                                    request.state.current_user
                                )
                                and not has_crm_owner_authority(
                                    request.state.current_user
                                )
                            )
                        )
                        else None
                    ),
                )
            except LeadCsvImportError as exc:
                import_error = str(exc)

        context = _add_leads_context(
            db,
            request,
            import_preview=import_preview,
            import_error=import_error,
            csv_content_b64=(
                base64.b64encode(content).decode("ascii")
                if import_error is None
                else None
            ),
        )

    return templates.TemplateResponse(
        request=request,
        name="add_leads.html",
        context=context,
        status_code=400 if import_error else 200,
    )


def _optional_selected_user_id(value: str) -> int | None:
    clean = (value or "").strip()
    if not clean:
        return None
    try:
        parsed = int(clean)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


@router.post("/leads/import", response_class=HTMLResponse)
async def import_leads_csv(
    request: Request,
    csv_content_b64: str = Form(...),
    selected_rows: list[int] = Form(default=[]),
    researcher_user_id: str = Form(default=""),
    business_development_owner_user_id: str = Form(default=""),
):
    import_error: str | None = None
    import_result = None
    content = b""

    try:
        content = base64.b64decode(csv_content_b64, validate=True)
    except (binascii.Error, ValueError):
        import_error = (
            "The previewed CSV could not be read. Preview the file again."
        )
    else:
        if len(content) > MAX_CSV_BYTES:
            import_error = (
                f"The CSV is too large. The maximum size is "
                f"{MAX_CSV_BYTES // 1_000_000} MB."
            )
        elif not selected_rows:
            import_error = "Select at least one row to import."

    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        owner_id = (
            request.state.current_user["id"]
            if is_owner(request.state.current_user)
            else get_primary_owner_id(db)
        )
        if owner_id is None:
            import_error = import_error or (
                "No owner account is available for lead assignment."
            )

        can_assign = has_crm_owner_authority(request.state.current_user)
        selected_researcher_id = (
            _optional_selected_user_id(researcher_user_id)
            if can_assign
            else None
        )
        selected_bd_owner_id = (
            _optional_selected_user_id(business_development_owner_user_id)
            if can_assign
            else None
        )

        if import_error is None:
            try:
                import_result = import_leads_from_csv(
                    db,
                    content,
                    pipeline_status_override=(
                        "new"
                        if (
                            is_lead_sourcer(request.state.current_user)
                            or is_relationship_manager(
                                request.state.current_user
                            )
                        )
                        else None
                    ),
                    created_by_user_id=request.state.current_user["id"],
                    assigned_to_user_id=owner_id,
                    business_development_owner_user_id=(
                        selected_bd_owner_id
                        if selected_bd_owner_id is not None
                        else (
                            request.state.current_user["id"]
                            if is_relationship_manager(
                                request.state.current_user
                            )
                            else None
                        )
                    ),
                    organization_id=organization_id,
                    selected_row_numbers=frozenset(selected_rows),
                    researcher_user_id=selected_researcher_id,
                )
            except LeadCsvImportError as exc:
                import_error = str(exc)

        context = _add_leads_context(
            db,
            request,
            import_result=import_result,
            import_error=import_error,
        )

    return templates.TemplateResponse(
        request=request,
        name="add_leads.html",
        context=context,
        status_code=400 if import_error else 200,
    )


@router.post("/leads")
def create_lead(
    request: Request,
    company: str = Form(...),
    contact_person: str = Form(...),
    source: str = Form(...),
    problem_opportunity: str = Form(...),
    why_mark_fits: str = Form(...),
    next_action: str = Form(...),
    job_title: str = Form(default=""),
    source_url: str = Form(default=""),
    pipeline_status: str = Form(default="new"),
    priority: str = Form(default="medium"),
    next_action_due_date: str = Form(default=""),
    notes: str = Form(default=""),
    request_key: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        owner_id = (
            request.state.current_user["id"]
            if is_owner(request.state.current_user)
            else get_primary_owner_id(db)
        )
        if owner_id is None:
            return RedirectResponse(
                url="/crm/leads/new?error=invalid",
                status_code=303,
            )

        try:
            result = create_lead_record(
                db,
                company=company,
                contact_person=contact_person,
                job_title=job_title,
                source=source,
                source_url=source_url,
                problem_opportunity=problem_opportunity,
                why_mark_fits=why_mark_fits,
                pipeline_status=(
                    "new"
                    if (
                        is_lead_sourcer(request.state.current_user)
                        or (
                            is_relationship_manager(
                                request.state.current_user
                            )
                            and not has_crm_owner_authority(
                                request.state.current_user
                            )
                        )
                    )
                    else pipeline_status
                ),
                priority=priority,
                next_action=next_action,
                next_action_due_date=next_action_due_date or None,
                notes=notes,
                request_key=request_key or None,
                created_by_user_id=request.state.current_user["id"],
                assigned_to_user_id=owner_id,
                business_development_owner_user_id=(
                    request.state.current_user["id"]
                    if is_relationship_manager(
                        request.state.current_user
                    )
                    else None
                ),
                organization_id=organization_id,
            )
        except ValueError:
            return RedirectResponse(
                url="/crm/leads/new?error=invalid",
                status_code=303,
            )
    notice = "created" if result.created else "duplicate"
    return RedirectResponse(
        url=f"/crm/leads/{result.lead['id']}?notice={notice}",
        status_code=303,
    )


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detail(request: Request, lead_id: int):
    user = request.state.current_user
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        lead = _lead_or_404(db, lead_id, request)
        show_deleted = (
            has_crm_owner_authority(user)
            and request.query_params.get("include_deleted") == "1"
        )
        try:
            activity_rows = list_lead_activities(
                db,
                lead_id,
                actor=user,
                include_deleted=show_deleted,
                organization_id=organization_id,
            )
        except LeadActivityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            ) from exc

        activities = []
        for row in reversed(activity_rows):
            activity = dict(row)
            activity["activity_at_input"] = str(
                activity["activity_at"]
            ).replace(" ", "T", 1)
            activity["can_correct"] = (
                _can_correct_activity_in_ui(
                    user,
                    activity,
                )
            )
            activities.append(activity)

        context = {
            "lead": lead,
            "activities": activities,
            "show_deleted_activities": show_deleted,
            "can_edit_research": can_edit_research(
                user,
                lead,
            ),
            "can_approve_outreach": can_approve_outreach(
                user,
                lead,
            ),
            "can_update_next_action": (
                can_update_relationship_next_action(
                    user,
                    lead,
                )
            ),
            "relationship_managers": (
                list_active_relationship_managers(
                    db,
                    organization_id=organization_id,
                )
                if has_crm_owner_authority(user)
                else []
            ),
            "can_edit_qualification": can_edit_qualification(
                user,
                lead,
            ),
            "can_decide_qualification": can_decide_qualification(
                user,
                lead,
            ),
            "existing_client": get_client_by_lead(
                db,
                lead_id,
                organization_id=organization_id,
            ),
            "can_manage_clients": can_manage_clients(user),
            "notice": _message(
                NOTICE_MESSAGES,
                request.query_params.get("notice"),
            ),
            "error": _message(
                ERROR_MESSAGES,
                request.query_params.get("error"),
            ),
            **_activity_form_context(
                db,
                user,
                organization_id=organization_id,
                lead=lead,
            ),
            **_shared_context(db, request),
        }
    return templates.TemplateResponse(
        request=request,
        name="lead_detail.html",
        context=context,
    )


@router.post("/leads/{lead_id}/activities")
def create_lead_activity(
    request: Request,
    lead_id: int,
    activity_type: str = Form(...),
    activity_at: str = Form(...),
    message_summary: str = Form(...),
    channel: str = Form(default="internal"),
    notes: str = Form(default=""),
    performed_by_user_id: str = Form(default=""),
    responsible_user_id: str = Form(default=""),
    response_status: str = Form(default="not_applicable"),
    next_follow_up_date: str = Form(default=""),
):
    user = request.state.current_user
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        _lead_or_404(db, lead_id, request)
        try:
            create_activity_record(
                db,
                lead_id,
                actor=user,
                activity_type=activity_type,
                activity_at=activity_at,
                channel=channel,
                message_summary=message_summary,
                notes=notes,
                performed_by_user_id=_optional_positive_form_id(
                    performed_by_user_id,
                    "Performed-by user ID",
                ),
                responsible_user_id=_optional_positive_form_id(
                    responsible_user_id,
                    "Responsible user ID",
                ),
                response_status=response_status,
                next_follow_up_date=(
                    next_follow_up_date.strip() or None
                ),
                organization_id=organization_id,
            )
        except LeadActivityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            ) from exc
        except LeadActivityPermissionError:
            return _activity_redirect(
                lead_id,
                error="activity_forbidden",
            )
        except ValueError:
            return _activity_redirect(
                lead_id,
                error="activity_invalid",
            )
    return _activity_redirect(
        lead_id,
        notice="activity_created",
    )


@router.post(
    "/leads/{lead_id}/activities/{activity_id}/correct"
)
def correct_lead_activity(
    request: Request,
    lead_id: int,
    activity_id: int,
    correction_reason: str = Form(...),
    activity_type: str = Form(...),
    activity_at: str = Form(...),
    message_summary: str = Form(...),
    channel: str = Form(default="internal"),
    notes: str = Form(default=""),
    performed_by_user_id: str = Form(default=""),
    responsible_user_id: str = Form(default=""),
    response_status: str = Form(default="not_applicable"),
    next_follow_up_date: str = Form(default=""),
):
    user = request.state.current_user
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        _lead_or_404(db, lead_id, request)
        _activity_for_lead_or_404(
            db,
            lead_id=lead_id,
            activity_id=activity_id,
            user=user,
            organization_id=organization_id,
        )
        try:
            correct_activity_record(
                db,
                activity_id,
                actor=user,
                correction_reason=correction_reason,
                activity_type=activity_type,
                activity_at=activity_at,
                channel=channel,
                message_summary=message_summary,
                notes=notes,
                performed_by_user_id=_optional_positive_form_id(
                    performed_by_user_id,
                    "Performed-by user ID",
                ),
                responsible_user_id=_optional_positive_form_id(
                    responsible_user_id,
                    "Responsible user ID",
                ),
                response_status=response_status,
                next_follow_up_date=(
                    next_follow_up_date.strip() or None
                ),
                organization_id=organization_id,
            )
        except LeadActivityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Lead activity not found",
            ) from exc
        except LeadActivityPermissionError:
            return _activity_redirect(
                lead_id,
                error="activity_forbidden",
            )
        except ValueError:
            return _activity_redirect(
                lead_id,
                error="activity_invalid",
            )
    return _activity_redirect(
        lead_id,
        notice="activity_corrected",
    )


@router.post(
    "/leads/{lead_id}/activities/{activity_id}/delete"
)
def delete_lead_activity(
    request: Request,
    lead_id: int,
    activity_id: int,
    correction_reason: str = Form(...),
):
    user = request.state.current_user
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        _lead_or_404(db, lead_id, request)
        _activity_for_lead_or_404(
            db,
            lead_id=lead_id,
            activity_id=activity_id,
            user=user,
            organization_id=organization_id,
        )
        try:
            soft_delete_activity_record(
                db,
                activity_id,
                actor=user,
                correction_reason=correction_reason,
                organization_id=organization_id,
            )
        except LeadActivityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Lead activity not found",
            ) from exc
        except LeadActivityPermissionError:
            return _activity_redirect(
                lead_id,
                error="activity_forbidden",
            )
        except ValueError:
            return _activity_redirect(
                lead_id,
                error="activity_invalid",
            )
    return _activity_redirect(
        lead_id,
        notice="activity_deleted",
    )

@router.get("/leads/{lead_id}/edit", response_class=HTMLResponse)
def edit_lead_page(request: Request, lead_id: int):
    with get_db() as db:
        lead = _lead_or_404(db, lead_id, request)
        context = {
            "lead": lead,
            "error": _message(ERROR_MESSAGES, request.query_params.get("error")),
            **_shared_context(db, request),
        }
    return templates.TemplateResponse(
        request=request,
        name="edit_lead.html",
        context=context,
    )


@router.post("/leads/{lead_id}/edit")
def edit_lead(
    request: Request,
    lead_id: int,
    company: str = Form(...),
    contact_person: str = Form(...),
    source: str = Form(...),
    problem_opportunity: str = Form(...),
    why_mark_fits: str = Form(...),
    next_action: str = Form(...),
    job_title: str = Form(default=""),
    source_url: str = Form(default=""),
    pipeline_status: str = Form(default="new"),
    priority: str = Form(default="medium"),
    next_action_due_date: str = Form(default=""),
    notes: str = Form(default=""),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        _lead_or_404(db, lead_id, request)
        try:
            update_owner_lead(
                db,
                lead_id,
                actor=request.state.current_user,
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
                next_action_due_date=next_action_due_date or None,
                notes=notes,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except LeadEditConflictError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}/edit?error=stale",
                status_code=303,
            )
        except LeadPermissionError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}/edit?error=forbidden",
                status_code=303,
            )
        except ValueError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}/edit?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/leads/{lead_id}?notice=updated",
        status_code=303,
    )


@router.post("/leads/{lead_id}/pipeline")
def update_pipeline(
    request: Request,
    lead_id: int,
    pipeline_status: str = Form(...),
    contact_activity_type: str = Form(default=""),
    contact_activity_at: str = Form(default=""),
    contact_channel: str = Form(default=""),
    contact_message_summary: str = Form(default=""),
    contact_notes: str = Form(default=""),
    contact_responsible_user_id: str = Form(default=""),
    contact_response_status: str = Form(default=""),
    contact_next_follow_up_date: str = Form(default=""),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        _lead_or_404(db, lead_id, request)
        try:
            change_pipeline_stage(
                db,
                lead_id,
                actor=request.state.current_user,
                pipeline_status=pipeline_status,
                contact_activity_type=(
                    _optional_form_text(contact_activity_type) or None
                ),
                contact_activity_at=(
                    _optional_form_text(contact_activity_at) or None
                ),
                contact_channel=(
                    _optional_form_text(contact_channel) or None
                ),
                contact_message_summary=(
                    _optional_form_text(contact_message_summary) or None
                ),
                contact_notes=_optional_form_text(contact_notes),
                contact_responsible_user_id=(
                    _optional_positive_form_id(
                        contact_responsible_user_id,
                        "Responsible user ID",
                    )
                ),
                contact_response_status=(
                    _optional_form_text(contact_response_status) or None
                ),
                contact_next_follow_up_date=(
                    _optional_form_text(contact_next_follow_up_date) or None
                ),
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except LeadEditConflictError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=stale",
                status_code=303,
            )
        except LeadActivityPermissionError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=forbidden",
                status_code=303,
            )
        except LeadPermissionError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=forbidden",
                status_code=303,
            )
        except LeadPipelineRuleError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=pipeline_rule",
                status_code=303,
            )
        except ValueError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/leads/{lead_id}?notice=pipeline",
        status_code=303,
    )

@router.post("/leads/{lead_id}/next-action")
def update_next_action(
    request: Request,
    lead_id: int,
    next_action: str = Form(...),
    next_action_due_date: str = Form(default=""),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        _lead_or_404(db, lead_id, request)
        try:
            update_next_action_for_actor(
                db,
                lead_id,
                actor=request.state.current_user,
                next_action=next_action,
                next_action_due_date=next_action_due_date or None,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except LeadEditConflictError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=stale",
                status_code=303,
            )
        except LeadPermissionError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=forbidden",
                status_code=303,
            )
        except ValueError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/leads/{lead_id}?notice=next_action",
        status_code=303,
    )


@router.post("/leads/{lead_id}/relationship-owner")
def update_relationship_owner(
    request: Request,
    lead_id: int,
    relationship_manager_user_id: str = Form(default=""),
    row_version: str = Form(default=""),
):
    manager_id = None
    if relationship_manager_user_id.strip():
        try:
            manager_id = int(relationship_manager_user_id)
        except ValueError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=invalid",
                status_code=303,
            )

    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        _lead_or_404(db, lead_id, request)
        try:
            assign_relationship_manager(
                db,
                lead_id,
                actor=request.state.current_user,
                relationship_manager_user_id=manager_id,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except LeadEditConflictError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=stale",
                status_code=303,
            )
        except LeadPermissionError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=forbidden",
                status_code=303,
            )
        except ValueError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=invalid",
                status_code=303,
            )

    return RedirectResponse(
        url=f"/crm/leads/{lead_id}?notice=relationship_owner",
        status_code=303,
    )


@router.get("/leads/{lead_id}/delete", response_class=HTMLResponse)
def delete_lead_page(request: Request, lead_id: int):
    with get_db() as db:
        lead = _lead_or_404(db, lead_id, request)
        context = {"lead": lead, "error": None, **_shared_context(db, request)}

    return templates.TemplateResponse(
        request=request,
        name="delete_lead.html",
        context=context,
    )


@router.post("/leads/{lead_id}/delete")
def delete_lead(
    request: Request,
    lead_id: int,
    confirmation: str = Form(default=""),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        lead = _lead_or_404(db, lead_id, request)
        if confirmation != "DELETE":
            return templates.TemplateResponse(
                request=request,
                name="delete_lead.html",
                context={
                    "lead": lead,
                    "error": ERROR_MESSAGES["confirmation"],
                    **_shared_context(db, request),
                },
                status_code=400,
            )
        try:
            delete_lead_record(
                db,
                lead_id,
                confirmed=True,
                actor=request.state.current_user,
                organization_id=_request_organization_id(db, request),
                expected_row_version=_expected_row_version(row_version),
            )
        except LeadEditConflictError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=stale",
                status_code=303,
            )
        except ValueError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=invalid",
                status_code=303,
            )

    return RedirectResponse(url="/crm?notice=deleted", status_code=303)
