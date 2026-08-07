from __future__ import annotations

from fastapi import (
    APIRouter,
    Form,
    HTTPException,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)

from app.database import get_db
from app.routes.shared import templates
from app.services.lead_research_permissions import (
    LeadPermissionError,
    can_edit_research,
)
from app.services.lead_research_workflow import (
    update_research_details,
)
from app.services.leads import get_lead
from app.services.workspace_context import require_request_organization_id


router = APIRouter(prefix="/crm")


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


def _editable_lead_or_404(
    db,
    lead_id: int,
    request: Request,
):
    lead = get_lead(
        db,
        lead_id,
        organization_id=_request_organization_id(db, request),
    )
    if (
        lead is None
        or not can_edit_research(
            request.state.current_user,
            lead,
        )
    ):
        # Do not reveal another user's lead or a
        # workflow state the actor cannot edit.
        raise HTTPException(
            status_code=404,
            detail="Lead not found",
        )
    return lead


@router.get(
    "/leads/{lead_id}/research/edit",
    response_class=HTMLResponse,
)
def edit_lead_research_page(
    request: Request,
    lead_id: int,
):
    with get_db() as db:
        lead = _editable_lead_or_404(
            db,
            lead_id,
            request,
        )

    return templates.TemplateResponse(
        request=request,
        name="edit_lead_research.html",
        context={
            "lead": lead,
            "current_user": (
                request.state.current_user
            ),
            "error": (
                "The research could not be saved. "
                "Check the required fields."
                if request.query_params.get("error")
                == "invalid"
                else None
            ),
        },
    )


@router.post(
    "/leads/{lead_id}/research/edit"
)
def edit_lead_research(
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
    next_action_due_date: str = Form(default=""),
    notes: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        _editable_lead_or_404(
            db,
            lead_id,
            request,
        )

        try:
            update_research_details(
                db,
                lead_id,
                actor=request.state.current_user,
                company=company,
                contact_person=contact_person,
                job_title=job_title,
                source=source,
                source_url=source_url,
                problem_opportunity=(
                    problem_opportunity
                ),
                why_mark_fits=why_mark_fits,
                next_action=next_action,
                next_action_due_date=(
                    next_action_due_date or None
                ),
                notes=notes,
                organization_id=organization_id,
            )
        except LeadPermissionError:
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            )
        except ValueError:
            return RedirectResponse(
                url=(
                    f"/crm/leads/{lead_id}/"
                    "research/edit?error=invalid"
                ),
                status_code=303,
            )

    return RedirectResponse(
        url=(
            f"/crm/leads/{lead_id}"
            "?notice=updated"
        ),
        status_code=303,
    )


@router.post(
    "/leads/{lead_id}/research/submit"
)
def submit_lead_research_for_review(
    request: Request,
    lead_id: int,
):
    from app.services.lead_research_permissions import (
        can_submit_for_review,
    )
    from app.services.lead_research_workflow import (
        submit_research_for_review,
    )

    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        lead = get_lead(
            db,
            lead_id,
            organization_id=organization_id,
        )
        if (
            lead is None
            or not can_submit_for_review(
                request.state.current_user,
                lead,
            )
        ):
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            )

        try:
            submit_research_for_review(
                db,
                lead_id,
                actor=request.state.current_user,
                organization_id=organization_id,
            )
        except LeadPermissionError:
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            )

    return RedirectResponse(
        url=(
            f"/crm/leads/{lead_id}"
            "?notice=research_submitted"
        ),
        status_code=303,
    )


@router.get(
    "/research-review",
    response_class=HTMLResponse,
)
def research_review_queue(
    request: Request,
):
    from app.services.access_control import is_owner
    from app.services.lead_research_workflow import (
        list_research_review_queue,
    )

    if not is_owner(
        request.state.current_user
    ):
        raise HTTPException(
            status_code=404,
            detail="Review queue not found",
        )

    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        leads = list_research_review_queue(
            db,
            organization_id=organization_id,
        )

    return templates.TemplateResponse(
        request=request,
        name="lead_research_review_queue.html",
        context={
            "leads": leads,
            "current_user": (
                request.state.current_user
            ),
        },
    )


@router.post(
    "/leads/{lead_id}/research/review"
)
def review_lead_research(
    request: Request,
    lead_id: int,
    decision: str = Form(...),
    review_notes: str = Form(default=""),
):
    from app.services.lead_research_permissions import (
        can_review_research,
    )
    from app.services.lead_research_workflow import (
        review_research,
    )

    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        lead = get_lead(
            db,
            lead_id,
            organization_id=organization_id,
        )
        if (
            lead is None
            or not can_review_research(
                request.state.current_user,
                lead,
            )
        ):
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            )

        try:
            reviewed = review_research(
                db,
                lead_id,
                actor=request.state.current_user,
                decision=decision,
                review_notes=review_notes,
                organization_id=organization_id,
            )
        except LeadPermissionError:
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            )
        except ValueError as exc:
            error_key = (
                "review_notes_required"
                if "notes are required"
                in str(exc).casefold()
                else "invalid_review"
            )
            return RedirectResponse(
                url=(
                    f"/crm/leads/{lead_id}"
                    f"?error={error_key}"
                ),
                status_code=303,
            )

    notice_by_status = {
        "approved": "research_approved",
        "changes_requested": (
            "research_changes_requested"
        ),
        "rejected": "research_rejected",
    }

    return RedirectResponse(
        url=(
            f"/crm/leads/{lead_id}"
            f"?notice={notice_by_status[reviewed['research_status']]}"
        ),
        status_code=303,
    )

@router.post(
    "/leads/{lead_id}/outreach/approve"
)
def approve_lead_outreach(
    request: Request,
    lead_id: int,
):
    from app.services.lead_pipeline_workflow import (
        approve_outreach,
    )
    from app.services.lead_research_permissions import (
        can_approve_outreach,
    )

    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        lead = get_lead(
            db,
            lead_id,
            organization_id=organization_id,
        )
        if (
            lead is None
            or not can_approve_outreach(
                request.state.current_user,
                lead,
            )
        ):
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            )

        try:
            approve_outreach(
                db,
                lead_id,
                actor=request.state.current_user,
                organization_id=organization_id,
            )
        except LeadPermissionError:
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            )

    return RedirectResponse(
        url=(
            f"/crm/leads/{lead_id}"
            "?notice=outreach_approved"
        ),
        status_code=303,
    )
