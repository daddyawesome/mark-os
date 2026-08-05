from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.database import get_db
from app.routes.shared import load_system_state, templates
from app.services.lead_csv_import import (
    CSV_HEADERS,
    LEAD_CSV_TEMPLATE_FILENAME,
    MAX_CSV_BYTES,
    MAX_CSV_ROWS,
    LeadCsvImportError,
    import_leads_from_csv,
    lead_csv_template_bytes,
)
from app.services.access_control import is_lead_sourcer, is_owner
from app.services.lead_research_permissions import can_edit_research
from app.services.team_users import get_primary_owner_id
from app.services.leads import (
    PIPELINE_STATUSES,
    PRIORITIES,
    create_lead as create_lead_record,
    delete_lead as delete_lead_record,
    get_crm_dashboard_metrics,
    get_lead,
    list_leads,
    update_lead as update_lead_record,
    update_lead_next_action as update_next_action_record,
    update_lead_pipeline as update_pipeline_record,
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
}
ERROR_MESSAGES = {
    "invalid": "The lead could not be saved. Check the required fields and allowed values.",
    "confirmation": 'Type DELETE exactly to archive this lead.',
    "forbidden": "Your account can add and review leads, but only the owner can edit pipeline actions or private MARK-OS data.",
    "review_notes_required": 'Review notes are required when requesting changes or rejecting.',
    "invalid_review": 'The research review decision could not be saved.',
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


def _lead_or_404(
    db,
    lead_id: int,
    request: Request | None = None,
):
    lead = get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    if request is not None:
        user = request.state.current_user
        if (
            is_lead_sourcer(user)
            and lead["created_by_user_id"] != user["id"]
        ):
            # Do not reveal whether another user's lead exists.
            raise HTTPException(status_code=404, detail="Lead not found")

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
    import_error: str | None = None,
) -> dict:
    return {
        "request_key": uuid4().hex,
        "notice": _message(NOTICE_MESSAGES, request.query_params.get("notice")),
        "error": _message(ERROR_MESSAGES, request.query_params.get("error")),
        "import_result": import_result,
        "import_error": import_error,
        "csv_headers": CSV_HEADERS,
        "max_csv_rows": MAX_CSV_ROWS,
        "max_csv_size_mb": MAX_CSV_BYTES // 1_000_000,
        **_shared_context(db, request),
    }


@router.get("", response_class=HTMLResponse)
def crm_dashboard(request: Request):
    user = request.state.current_user
    creator_filter = user["id"] if is_lead_sourcer(user) else None

    with get_db() as db:
        metrics = get_crm_dashboard_metrics(
            db,
            created_by_user_id=creator_filter,
        )
        context = {
            "leads": list_leads(
                db,
                created_by_user_id=creator_filter,
            ),
            "metric_cards": [
                {"label": label, "value": metrics[key]}
                for label, key in METRIC_DEFINITIONS
            ],
            "notice": _message(NOTICE_MESSAGES, request.query_params.get("notice")),
            "error": _message(ERROR_MESSAGES, request.query_params.get("error")),
            **_shared_context(db, request),
        }
    return templates.TemplateResponse(
        request=request,
        name="client_hunting.html",
        context=context,
    )


# These static routes must stay above /leads/{lead_id}.
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
                        if is_lead_sourcer(request.state.current_user)
                        else None
                    ),
                    created_by_user_id=request.state.current_user["id"],
                    assigned_to_user_id=owner_id,
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
                    if is_lead_sourcer(request.state.current_user)
                    else pipeline_status
                ),
                priority=priority,
                next_action=next_action,
                next_action_due_date=next_action_due_date or None,
                notes=notes,
                request_key=request_key or None,
                created_by_user_id=request.state.current_user["id"],
                assigned_to_user_id=owner_id,
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
    with get_db() as db:
        lead = _lead_or_404(db, lead_id, request)
        context = {
            "lead": lead,
            "can_edit_research": can_edit_research(
                request.state.current_user,
                lead,
            ),
            "notice": _message(NOTICE_MESSAGES, request.query_params.get("notice")),
            "error": _message(ERROR_MESSAGES, request.query_params.get("error")),
            **_shared_context(db, request),
        }
    return templates.TemplateResponse(
        request=request,
        name="lead_detail.html",
        context=context,
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
            update_lead_record(
                db,
                lead_id,
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
    lead_id: int,
    pipeline_status: str = Form(...),
):
    with get_db() as db:
        _lead_or_404(db, lead_id)
        try:
            update_pipeline_record(
                db,
                lead_id,
                pipeline_status=pipeline_status,
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
    lead_id: int,
    next_action: str = Form(...),
    next_action_due_date: str = Form(default=""),
):
    with get_db() as db:
        _lead_or_404(db, lead_id)
        try:
            update_next_action_record(
                db,
                lead_id,
                next_action=next_action,
                next_action_due_date=next_action_due_date or None,
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
