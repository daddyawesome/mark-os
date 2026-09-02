from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import templates
from app.services.lead_qualification_permissions import (
    LeadQualificationPermissionError,
    can_edit_qualification,
)
from app.services.lead_qualification_workflow import (
    QUALIFICATION_TEXT_FIELDS,
    decide_qualification,
    update_qualification_details,
)
from app.services.leads import LeadEditConflictError, get_lead
from app.services.workspace_context import require_request_organization_id


router = APIRouter(prefix="/crm")


def _request_organization_id(db, request: Request) -> int:
    try:
        return require_request_organization_id(request, db=db)
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=403,
            detail="An authorized CRM workspace is required",
        ) from exc


def _expected_row_version(value: object) -> int | None:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
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


def _editable_lead_or_404(db, lead_id: int, request: Request):
    lead = get_lead(
        db,
        lead_id,
        organization_id=_request_organization_id(db, request),
    )
    if lead is None or not can_edit_qualification(
        request.state.current_user,
        lead,
    ):
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get(
    "/leads/{lead_id}/qualification/edit",
    response_class=HTMLResponse,
)
def edit_lead_qualification_page(request: Request, lead_id: int):
    with get_db() as db:
        lead = _editable_lead_or_404(db, lead_id, request)

    error_key = request.query_params.get("error")
    return templates.TemplateResponse(
        request=request,
        name="edit_lead_qualification.html",
        context={
            "lead": lead,
            "current_user": request.state.current_user,
            "error": (
                "This lead changed in another session. Reload the latest "
                "version and try again."
                if error_key == "stale"
                else (
                    "The qualification details could not be saved. Check "
                    "the fields and try again."
                    if error_key == "invalid"
                    else None
                )
            ),
        },
    )


@router.post("/leads/{lead_id}/qualification/edit")
def edit_lead_qualification(
    request: Request,
    lead_id: int,
    business_problem: str = Form(default=""),
    business_impact: str = Form(default=""),
    current_process: str = Form(default=""),
    current_tools: str = Form(default=""),
    estimated_hours_wasted: str = Form(default=""),
    urgency: str = Form(default=""),
    budget_range: str = Form(default=""),
    decision_maker: str = Form(default=""),
    desired_result: str = Form(default=""),
    meeting_notes: str = Form(default=""),
    recommended_service: str = Form(default=""),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            update_qualification_details(
                db,
                lead_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
                business_problem=business_problem,
                business_impact=business_impact,
                current_process=current_process,
                current_tools=current_tools,
                estimated_hours_wasted=estimated_hours_wasted,
                urgency=urgency,
                budget_range=budget_range,
                decision_maker=decision_maker,
                desired_result=desired_result,
                meeting_notes=meeting_notes,
                recommended_service=recommended_service,
            )
        except LeadEditConflictError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}/qualification/edit?error=stale",
                status_code=303,
            )
        except LeadQualificationPermissionError:
            raise HTTPException(status_code=404, detail="Lead not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}/qualification/edit?error=invalid",
                status_code=303,
            )

    return RedirectResponse(
        url=f"/crm/leads/{lead_id}?notice=qualification_updated",
        status_code=303,
    )


@router.post("/leads/{lead_id}/qualification/decide")
def decide_lead_qualification(
    request: Request,
    lead_id: int,
    decision: str = Form(...),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        lead = get_lead(db, lead_id, organization_id=organization_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        try:
            decide_qualification(
                db,
                lead_id,
                actor=request.state.current_user,
                decision=decision,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except LeadEditConflictError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=stale",
                status_code=303,
            )
        except LeadQualificationPermissionError:
            raise HTTPException(status_code=404, detail="Lead not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=invalid",
                status_code=303,
            )

    return RedirectResponse(
        url=f"/crm/leads/{lead_id}?notice=qualification_decided",
        status_code=303,
    )
