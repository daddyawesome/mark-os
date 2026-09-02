from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import templates
from app.services.leads import get_lead
from app.services.proposal_permissions import (
    ProposalPermissionError,
    can_manage_proposals,
    can_view_proposals_for_lead,
)
from app.services.proposals import (
    ProposalStateError,
    approve_proposal,
    create_proposal,
    get_proposal,
    list_proposals_for_lead,
    record_proposal_decision,
    send_proposal,
    submit_proposal_for_internal_review,
    update_proposal,
)
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


def _expected_row_version(value: str) -> int | None:
    clean = (value or "").strip()
    if not clean:
        return None
    try:
        parsed = int(clean)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _price_to_minor_units(value: str) -> int | None:
    clean = (value or "").strip()
    if not clean:
        return None
    try:
        return round(float(clean) * 100)
    except ValueError:
        raise ValueError("Price must be a number.") from None


def _viewable_lead_or_404(db, request: Request, lead_id: int, organization_id: int):
    lead = get_lead(db, lead_id, organization_id=organization_id)
    if lead is None or not can_view_proposals_for_lead(
        request.state.current_user, lead
    ):
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get("/leads/{lead_id}/proposals", response_class=HTMLResponse)
def list_lead_proposals_page(request: Request, lead_id: int):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        lead = _viewable_lead_or_404(db, request, lead_id, organization_id)
        proposals = list_proposals_for_lead(
            db, lead_id, organization_id=organization_id
        )

    return templates.TemplateResponse(
        request=request,
        name="lead_proposals.html",
        context={
            "current_user": request.state.current_user,
            "lead": lead,
            "proposals": proposals,
            "can_manage": can_manage_proposals(request.state.current_user),
        },
    )


@router.post("/leads/{lead_id}/proposals")
def create_lead_proposal(
    request: Request,
    lead_id: int,
    service_offered: str = Form(...),
    engagement_type: str = Form(default=""),
    proposed_price: str = Form(default=""),
    expected_monthly_value: str = Form(default=""),
    currency: str = Form(default="PHP"),
    proposal_url: str = Form(default=""),
    proposal_expires_at: str = Form(default=""),
    probability: str = Form(default=""),
    follow_up_date: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            proposal = create_proposal(
                db,
                actor=request.state.current_user,
                organization_id=organization_id,
                lead_id=lead_id,
                service_offered=service_offered,
                engagement_type=engagement_type,
                proposed_price_amount_minor_units=_price_to_minor_units(
                    proposed_price
                ),
                expected_monthly_value_amount_minor_units=_price_to_minor_units(
                    expected_monthly_value
                ),
                currency=currency,
                proposal_url=proposal_url,
                proposal_expires_at=proposal_expires_at or None,
                probability=int(probability) if probability.strip() else None,
                follow_up_date=follow_up_date or None,
            )
        except ProposalPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}/proposals?error=invalid",
                status_code=303,
            )

    return RedirectResponse(
        url=f"/crm/leads/{lead_id}/proposals/{proposal['id']}?notice=created",
        status_code=303,
    )


def _proposal_or_404(db, request: Request, lead_id: int, proposal_id: int, organization_id: int):
    lead = _viewable_lead_or_404(db, request, lead_id, organization_id)
    proposal = get_proposal(db, proposal_id, organization_id=organization_id)
    if proposal is None or int(proposal["lead_id"]) != int(lead_id):
        raise HTTPException(status_code=404, detail="Proposal not found")
    return lead, proposal


@router.get(
    "/leads/{lead_id}/proposals/{proposal_id}",
    response_class=HTMLResponse,
)
def lead_proposal_detail_page(
    request: Request,
    lead_id: int,
    proposal_id: int,
    notice: str | None = None,
    error: str | None = None,
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        lead, proposal = _proposal_or_404(
            db, request, lead_id, proposal_id, organization_id
        )

    return templates.TemplateResponse(
        request=request,
        name="lead_proposal_detail.html",
        context={
            "current_user": request.state.current_user,
            "lead": lead,
            "proposal": proposal,
            "can_manage": can_manage_proposals(request.state.current_user),
            "notice": notice,
            "error": error,
        },
    )


@router.post("/leads/{lead_id}/proposals/{proposal_id}/edit")
def edit_lead_proposal(
    request: Request,
    lead_id: int,
    proposal_id: int,
    service_offered: str = Form(...),
    engagement_type: str = Form(default=""),
    proposed_price: str = Form(default=""),
    expected_monthly_value: str = Form(default=""),
    currency: str = Form(default="PHP"),
    proposal_url: str = Form(default=""),
    proposal_expires_at: str = Form(default=""),
    probability: str = Form(default=""),
    follow_up_date: str = Form(default=""),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            update_proposal(
                db,
                proposal_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
                service_offered=service_offered,
                engagement_type=engagement_type,
                proposed_price_amount_minor_units=_price_to_minor_units(
                    proposed_price
                ),
                expected_monthly_value_amount_minor_units=_price_to_minor_units(
                    expected_monthly_value
                ),
                currency=currency,
                proposal_url=proposal_url,
                proposal_expires_at=proposal_expires_at or None,
                probability=int(probability) if probability.strip() else None,
                follow_up_date=follow_up_date or None,
            )
        except ProposalPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except (ValueError, ProposalStateError) as exc:
            error_key = (
                "stale"
                if "another session" in str(exc)
                else "invalid"
            )
            return RedirectResponse(
                url=(
                    f"/crm/leads/{lead_id}/proposals/{proposal_id}"
                    f"?error={error_key}"
                ),
                status_code=303,
            )

    return RedirectResponse(
        url=f"/crm/leads/{lead_id}/proposals/{proposal_id}?notice=updated",
        status_code=303,
    )


def _lifecycle_redirect_error(exc: Exception, lead_id: int, proposal_id: int) -> RedirectResponse:
    error_key = "stale" if "another session" in str(exc) else "invalid"
    return RedirectResponse(
        url=f"/crm/leads/{lead_id}/proposals/{proposal_id}?error={error_key}",
        status_code=303,
    )


@router.post("/leads/{lead_id}/proposals/{proposal_id}/submit-review")
def submit_lead_proposal_for_review(
    request: Request,
    lead_id: int,
    proposal_id: int,
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            submit_proposal_for_internal_review(
                db,
                proposal_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except ProposalPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except (ValueError, ProposalStateError) as exc:
            return _lifecycle_redirect_error(exc, lead_id, proposal_id)
    return RedirectResponse(
        url=f"/crm/leads/{lead_id}/proposals/{proposal_id}?notice=submitted",
        status_code=303,
    )


@router.post("/leads/{lead_id}/proposals/{proposal_id}/approve")
def approve_lead_proposal(
    request: Request,
    lead_id: int,
    proposal_id: int,
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            approve_proposal(
                db,
                proposal_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except ProposalPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except (ValueError, ProposalStateError) as exc:
            return _lifecycle_redirect_error(exc, lead_id, proposal_id)
    return RedirectResponse(
        url=f"/crm/leads/{lead_id}/proposals/{proposal_id}?notice=approved",
        status_code=303,
    )


@router.post("/leads/{lead_id}/proposals/{proposal_id}/send")
def send_lead_proposal(
    request: Request,
    lead_id: int,
    proposal_id: int,
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            send_proposal(
                db,
                proposal_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except ProposalPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except (ValueError, ProposalStateError) as exc:
            return _lifecycle_redirect_error(exc, lead_id, proposal_id)
    return RedirectResponse(
        url=f"/crm/leads/{lead_id}/proposals/{proposal_id}?notice=sent",
        status_code=303,
    )


@router.post("/leads/{lead_id}/proposals/{proposal_id}/decision")
def decide_lead_proposal(
    request: Request,
    lead_id: int,
    proposal_id: int,
    decision: str = Form(...),
    decision_reason: str = Form(default=""),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            record_proposal_decision(
                db,
                proposal_id,
                actor=request.state.current_user,
                decision=decision,
                decision_reason=decision_reason,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except ProposalPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except (ValueError, ProposalStateError) as exc:
            error_key = (
                "stale" if "another session" in str(exc) else "invalid"
            )
            return RedirectResponse(
                url=(
                    f"/crm/leads/{lead_id}/proposals/{proposal_id}"
                    f"?error={error_key}"
                ),
                status_code=303,
            )

    return RedirectResponse(
        url=f"/crm/leads/{lead_id}/proposals/{proposal_id}?notice=decided",
        status_code=303,
    )
