from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.db.outreach_templates import TEMPLATE_CATEGORIES
from app.routes.shared import templates
from app.services.access_control import has_crm_owner_authority
from app.services.lead_research_permissions import can_view_lead
from app.services.leads import get_lead
from app.services.outreach_templates import (
    OutreachTemplatePermissionError,
    archive_template,
    create_template,
    get_template,
    list_templates,
    render_template,
    set_template_approval,
    update_template,
)
from app.services.workspace_context import require_request_organization_id


router = APIRouter(prefix="/crm/templates")

CATEGORY_LABELS = {
    "warm_introduction": "Warm introduction",
    "linkedin_message": "LinkedIn message",
    "email_introduction": "Email introduction",
    "follow_up": "3-5 business-day follow-up",
    "meeting_handoff": "Meeting handoff",
    "objection_response": "Common-objection response",
}

NOTICE_MESSAGES = {
    "created": "Template created as a draft. Approve it before it is available to Relationship Managers.",
    "updated": "Template updated.",
    "approved": "Template approved and now available to Relationship Managers.",
    "unapproved": "Template approval revoked.",
    "archived": "Template archived.",
}

ERROR_MESSAGES = {
    "invalid": "The template could not be saved. Check the required fields.",
    "stale": "This template changed in another session. Reload and try again.",
}


def _message(mapping: dict[str, str], key: str | None) -> str | None:
    return mapping.get(key or "")


def _request_organization_id(db, request: Request) -> int:
    try:
        return require_request_organization_id(request, db=db)
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=403,
            detail="An authorized CRM workspace is required",
        ) from exc


def _expected_row_version(value: str) -> int | None:
    clean = (value or "").strip()
    if not clean:
        return None
    try:
        parsed = int(clean)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _viewable_lead_id(db, request: Request, organization_id: int, lead_id: int | None) -> int | None:
    if lead_id is None:
        return None
    lead = get_lead(db, lead_id, organization_id=organization_id)
    if lead is None or not can_view_lead(request.state.current_user, lead):
        return None
    return int(lead["id"])


@router.get("", response_class=HTMLResponse)
def list_outreach_templates(
    request: Request,
    notice: str | None = None,
    error: str | None = None,
    lead_id: int | None = None,
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        can_manage = has_crm_owner_authority(request.state.current_user)
        items = list_templates(
            db,
            organization_id=organization_id,
            approved_only=not can_manage,
        )
        safe_lead_id = _viewable_lead_id(db, request, organization_id, lead_id)

    return templates.TemplateResponse(
        request=request,
        name="outreach_templates.html",
        context={
            "current_user": request.state.current_user,
            "can_manage_templates": can_manage,
            "templates": items,
            "category_labels": CATEGORY_LABELS,
            "notice": _message(NOTICE_MESSAGES, notice),
            "error": _message(ERROR_MESSAGES, error),
            "lead_id": safe_lead_id,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_outreach_template_page(request: Request):
    if not has_crm_owner_authority(request.state.current_user):
        raise HTTPException(status_code=404, detail="Not found")
    return templates.TemplateResponse(
        request=request,
        name="outreach_template_form.html",
        context={
            "current_user": request.state.current_user,
            "template": None,
            "categories": TEMPLATE_CATEGORIES,
            "category_labels": CATEGORY_LABELS,
        },
    )


@router.post("")
def create_outreach_template(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    body: str = Form(...),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            created = create_template(
                db,
                actor=request.state.current_user,
                organization_id=organization_id,
                title=title,
                category=category,
                body=body,
            )
        except OutreachTemplatePermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(
                url="/crm/templates/new?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/templates/{created['id']}/edit?notice=created",
        status_code=303,
    )


def _template_or_404(db, request: Request, template_id: int, organization_id: int):
    template = get_template(db, template_id, organization_id=organization_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.get("/{template_id}/edit", response_class=HTMLResponse)
def edit_outreach_template_page(
    request: Request,
    template_id: int,
    notice: str | None = None,
    error: str | None = None,
):
    if not has_crm_owner_authority(request.state.current_user):
        raise HTTPException(status_code=404, detail="Not found")
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        template = _template_or_404(db, request, template_id, organization_id)
    return templates.TemplateResponse(
        request=request,
        name="outreach_template_form.html",
        context={
            "current_user": request.state.current_user,
            "template": template,
            "categories": TEMPLATE_CATEGORIES,
            "category_labels": CATEGORY_LABELS,
            "notice": _message(NOTICE_MESSAGES, notice),
            "error": _message(ERROR_MESSAGES, error),
        },
    )


@router.post("/{template_id}/edit")
def edit_outreach_template(
    request: Request,
    template_id: int,
    title: str = Form(...),
    category: str = Form(...),
    body: str = Form(...),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            update_template(
                db,
                template_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                title=title,
                category=category,
                body=body,
                expected_row_version=_expected_row_version(row_version),
            )
        except OutreachTemplatePermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError as exc:
            error_key = "stale" if "another session" in str(exc) else "invalid"
            return RedirectResponse(
                url=f"/crm/templates/{template_id}/edit?error={error_key}",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/templates/{template_id}/edit?notice=updated",
        status_code=303,
    )


@router.post("/{template_id}/approve")
def approve_outreach_template(
    request: Request,
    template_id: int,
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            set_template_approval(
                db,
                template_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                approved=True,
                expected_row_version=_expected_row_version(row_version),
            )
        except OutreachTemplatePermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(url="/crm/templates?error=stale", status_code=303)
    return RedirectResponse(url="/crm/templates?notice=approved", status_code=303)


@router.post("/{template_id}/unapprove")
def unapprove_outreach_template(
    request: Request,
    template_id: int,
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            set_template_approval(
                db,
                template_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                approved=False,
                expected_row_version=_expected_row_version(row_version),
            )
        except OutreachTemplatePermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(url="/crm/templates?error=stale", status_code=303)
    return RedirectResponse(url="/crm/templates?notice=unapproved", status_code=303)


@router.post("/{template_id}/archive")
def delete_outreach_template(
    request: Request,
    template_id: int,
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            archive_template(
                db,
                template_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except OutreachTemplatePermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(url="/crm/templates?error=stale", status_code=303)
    return RedirectResponse(url="/crm/templates?notice=archived", status_code=303)


def _lead_variable_defaults(lead) -> dict[str, str]:
    if lead is None:
        return {}
    return {
        "company": str(lead["company"] or ""),
        "contact_person": str(lead["contact_person"] or ""),
        "next_action": str(lead["next_action"] or ""),
    }


@router.get("/{template_id}/use", response_class=HTMLResponse)
def use_outreach_template_page(
    request: Request,
    template_id: int,
    lead_id: int | None = None,
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        can_manage = has_crm_owner_authority(request.state.current_user)
        template = get_template(db, template_id, organization_id=organization_id)
        if template is None or (not template["approved"] and not can_manage):
            raise HTTPException(status_code=404, detail="Template not found")
        safe_lead_id = _viewable_lead_id(db, request, organization_id, lead_id)
        lead = (
            get_lead(db, safe_lead_id, organization_id=organization_id)
            if safe_lead_id is not None
            else None
        )

    return templates.TemplateResponse(
        request=request,
        name="outreach_template_use.html",
        context={
            "current_user": request.state.current_user,
            "template": template,
            "category_labels": CATEGORY_LABELS,
            "rendered_preview": None,
            "lead": lead,
            "submitted_variables": _lead_variable_defaults(lead),
        },
    )


@router.post("/{template_id}/use", response_class=HTMLResponse)
async def render_outreach_template_preview(
    request: Request,
    template_id: int,
):
    form = await request.form()
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        can_manage = has_crm_owner_authority(request.state.current_user)
        template = get_template(db, template_id, organization_id=organization_id)
        if template is None or (not template["approved"] and not can_manage):
            raise HTTPException(status_code=404, detail="Template not found")
        raw_lead_id = str(form.get("lead_id") or "").strip()
        parsed_lead_id = int(raw_lead_id) if raw_lead_id.isdigit() else None
        safe_lead_id = _viewable_lead_id(
            db,
            request,
            organization_id,
            parsed_lead_id,
        )
        lead = (
            get_lead(db, safe_lead_id, organization_id=organization_id)
            if safe_lead_id is not None
            else None
        )

    variables = {
        name: str(form.get(f"var_{name}", "") or "")
        for name in template["variables"]
    }
    rendered_preview = render_template(template["body"], variables)

    return templates.TemplateResponse(
        request=request,
        name="outreach_template_use.html",
        context={
            "current_user": request.state.current_user,
            "template": template,
            "category_labels": CATEGORY_LABELS,
            "rendered_preview": rendered_preview,
            "submitted_variables": variables,
            "lead": lead,
        },
    )
