from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

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
    is_lead_sourcer,
    is_owner,
    is_relationship_manager,
)
from app.services.lead_research_permissions import (
    LeadPermissionError,
    can_approve_outreach,
    can_edit_research,
    can_view_lead,
)
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
from app.services.team_users import get_primary_owner_id
from app.services.relationship_manager import (
    assign_relationship_manager,
    can_update_relationship_next_action,
    list_active_relationship_managers,
    update_next_action_for_actor,
)
from app.services.leads import (
    PIPELINE_STATUSES,
    PRIORITIES,
    create_lead as create_lead_record,
    delete_lead as delete_lead_record,
    get_crm_dashboard_metrics,
    get_lead,
)

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
    "research_submitted": "Research submitted for Owner review.",
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
}
ERROR_MESSAGES = {
    "invalid": "The lead could not be saved. Check the required fields and allowed values.",
    "confirmation": 'Type DELETE exactly to archive this lead.',
    "forbidden": "Your account can add and review leads, but only the owner can edit pipeline actions or private MARK-OS data.",
    "review_notes_required": 'Review notes are required when requesting changes or rejecting.',
    "invalid_review": 'The research review decision could not be saved.',
    "pipeline_rule": "That pipeline move is not allowed. Contacted requires approved research, outreach approval, and a complete contact audit; Proposal requires Meeting; Won requires Proposal.",
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

def _activity_form_context(
    db,
    user,
) -> dict:
    can_create = is_owner(user) or is_lead_sourcer(user)
    activity_types = (
        ACTIVITY_TYPES
        if is_owner(user)
        else tuple(
            activity_type
            for activity_type in ACTIVITY_TYPES
            if activity_type in LEAD_SOURCER_ACTIVITY_TYPES
        )
        if is_lead_sourcer(user)
        else ()
    )
    channels = CHANNELS if is_owner(user) else ("internal",)
    return {
        "can_create_activity": can_create,
        "activity_type_options": activity_types,
        "activity_channel_options": channels,
        "activity_response_status_options": RESPONSE_STATUSES,
        "contact_activity_type_options": (
            CONTACT_ACTIVITY_TYPES
            if is_owner(user)
            else ()
        ),
        "contact_channel_options": (
            CONTACT_CHANNELS
            if is_owner(user)
            else ()
        ),
        "contact_response_status_options": (
            CONTACT_RESPONSE_STATUSES
            if is_owner(user)
            else ()
        ),
        "activity_users": (
            list_active_activity_users(db, actor=user)
            if can_create
            else []
        ),
    }

def _can_correct_activity_in_ui(
    user,
    activity: dict,
) -> bool:
    if is_owner(user):
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
):
    try:
        activity = get_activity_record(
            db,
            activity_id,
            actor=user,
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
    request: Request | None = None,
):
    lead = get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(
            status_code=404,
            detail="Lead not found",
        )

    if (
        request is not None
        and not can_view_lead(
            request.state.current_user,
            lead,
        )
    ):
        # Do not reveal whether another user's lead
        # exists.
        raise HTTPException(
            status_code=404,
            detail="Lead not found",
        )

    return lead

def _shared_context(db, request: Request) -> dict:
    user = request.state.current_user
    owner = is_owner(user)
    return {
        "pipeline_options": PIPELINE_OPTIONS,
        "priority_options": PRIORITY_OPTIONS,
        "system_state": load_system_state(db) if owner else None,
        "current_user": user,
        "can_manage_crm": owner,
    }


def _add_leads_context(
    db,
    request: Request,
    *,
    import_result=None,
    import_preview=None,
    import_error: str | None = None,
) -> dict:
    return {
        "request_key": uuid4().hex,
        "notice": _message(NOTICE_MESSAGES, request.query_params.get("notice")),
        "error": _message(ERROR_MESSAGES, request.query_params.get("error")),
        "import_result": import_result,
        "import_preview": import_preview,
        "import_error": import_error,
        "csv_headers": CSV_HEADERS,
        "max_csv_rows": MAX_CSV_ROWS,
        "max_csv_size_mb": MAX_CSV_BYTES // 1_000_000,
        **_shared_context(db, request),
    }


@router.get("", response_class=HTMLResponse)
def crm_dashboard(request: Request):
    user = request.state.current_user

    with get_db() as db:
        dashboard = build_role_aware_crm_dashboard(
            db,
            user,
        )
        metric_cards = dashboard["metric_cards"]

        if is_owner(user):
            metrics = get_crm_dashboard_metrics(db)
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
        try:
            command_center = build_follow_up_command_center(
                db,
                user,
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
        context = _add_leads_context(db, request)
    return templates.TemplateResponse(
        request=request,
        name="add_leads.html",
        context=context,
    )


@router.get("/leads/import/template")
def download_lead_csv_template():
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
        if import_error is None:
            try:
                import_preview = preview_leads_from_csv(
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
                )
            except LeadCsvImportError as exc:
                import_error = str(exc)

        context = _add_leads_context(
            db,
            request,
            import_preview=import_preview,
            import_error=import_error,
        )

    return templates.TemplateResponse(
        request=request,
        name="add_leads.html",
        context=context,
        status_code=400 if import_error else 200,
    )


@router.post("/leads/import", response_class=HTMLResponse)
async def import_leads_csv(
    request: Request,
    csv_file: UploadFile = File(...),
):
    filename = (csv_file.filename or "").strip()
    content = b""
    import_error: str | None = None
    import_result = None

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
        owner_id = (
            request.state.current_user["id"]
            if is_owner(request.state.current_user)
            else get_primary_owner_id(db)
        )
        if owner_id is None:
            import_error = "No owner account is available for lead assignment."

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
                        request.state.current_user["id"]
                        if is_relationship_manager(
                            request.state.current_user
                        )
                        else None
                    ),
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
                        or is_relationship_manager(
                            request.state.current_user
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
        lead = _lead_or_404(db, lead_id, request)
        show_deleted = (
            is_owner(user)
            and request.query_params.get("include_deleted") == "1"
        )
        try:
            activity_rows = list_lead_activities(
                db,
                lead_id,
                actor=user,
                include_deleted=show_deleted,
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
                list_active_relationship_managers(db)
                if is_owner(user)
                else []
            ),
            "notice": _message(
                NOTICE_MESSAGES,
                request.query_params.get("notice"),
            ),
            "error": _message(
                ERROR_MESSAGES,
                request.query_params.get("error"),
            ),
            **_activity_form_context(db, user),
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
        _lead_or_404(db, lead_id, request)
        _activity_for_lead_or_404(
            db,
            lead_id=lead_id,
            activity_id=activity_id,
            user=user,
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
        _lead_or_404(db, lead_id, request)
        _activity_for_lead_or_404(
            db,
            lead_id=lead_id,
            activity_id=activity_id,
            user=user,
        )
        try:
            soft_delete_activity_record(
                db,
                activity_id,
                actor=user,
                correction_reason=correction_reason,
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
        lead = _lead_or_404(db, lead_id)
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
):
    with get_db() as db:
        _lead_or_404(db, lead_id)
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
):
    with get_db() as db:
        _lead_or_404(db, lead_id)
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
):
    with get_db() as db:
        _lead_or_404(db, lead_id, request)
        try:
            update_next_action_for_actor(
                db,
                lead_id,
                actor=request.state.current_user,
                next_action=next_action,
                next_action_due_date=next_action_due_date or None,
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
        _lead_or_404(db, lead_id)
        try:
            assign_relationship_manager(
                db,
                lead_id,
                actor=request.state.current_user,
                relationship_manager_user_id=manager_id,
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
        lead = _lead_or_404(db, lead_id)
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
):
    with get_db() as db:
        lead = _lead_or_404(db, lead_id)
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
        delete_lead_record(db, lead_id, confirmed=True)

    return RedirectResponse(url="/crm?notice=deleted", status_code=303)
