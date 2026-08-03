from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import load_system_state, templates
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
    "pipeline": "Pipeline status updated.",
    "next_action": "Next action updated.",
    "deleted": "Lead archived. Its quest history was preserved.",
}
ERROR_MESSAGES = {
    "invalid": "The lead could not be saved. Check the required fields and allowed values.",
    "confirmation": 'Type DELETE exactly to archive this lead.',
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


def _lead_or_404(db, lead_id: int):
    lead = get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def _shared_context(db) -> dict:
    return {
        "pipeline_options": PIPELINE_OPTIONS,
        "priority_options": PRIORITY_OPTIONS,
        "system_state": load_system_state(db),
    }


@router.get("", response_class=HTMLResponse)
def crm_dashboard(request: Request):
    with get_db() as db:
        metrics = get_crm_dashboard_metrics(db)
        context = {
            "leads": list_leads(db),
            "metric_cards": [
                {"label": label, "value": metrics[key]}
                for label, key in METRIC_DEFINITIONS
            ],
            "request_key": uuid4().hex,
            "notice": _message(NOTICE_MESSAGES, request.query_params.get("notice")),
            "error": _message(ERROR_MESSAGES, request.query_params.get("error")),
            **_shared_context(db),
        }

    return templates.TemplateResponse(
        request=request,
        name="client_hunting.html",
        context=context,
    )


@router.post("/leads")
def create_lead(
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
                pipeline_status=pipeline_status,
                priority=priority,
                next_action=next_action,
                next_action_due_date=next_action_due_date or None,
                notes=notes,
                request_key=request_key or None,
            )
        except ValueError:
            return RedirectResponse(url="/crm?error=invalid", status_code=303)

    notice = "created" if result.created else "duplicate"
    return RedirectResponse(
        url=f"/crm/leads/{result.lead['id']}?notice={notice}",
        status_code=303,
    )


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detail(request: Request, lead_id: int):
    with get_db() as db:
        lead = _lead_or_404(db, lead_id)
        context = {
            "lead": lead,
            "notice": _message(NOTICE_MESSAGES, request.query_params.get("notice")),
            "error": _message(ERROR_MESSAGES, request.query_params.get("error")),
            **_shared_context(db),
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
            **_shared_context(db),
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
        context = {"lead": lead, "error": None, **_shared_context(db)}

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
                    **_shared_context(db),
                },
                status_code=400,
            )

        # The destructive service flag is only supplied after exact confirmation.
        delete_lead_record(db, lead_id, confirmed=True)

    return RedirectResponse(url="/crm?notice=deleted", status_code=303)
