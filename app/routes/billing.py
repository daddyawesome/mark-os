from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import templates
from app.services.billing import (
    BillingPermissionError,
    cancel_billing_arrangement,
    compute_engagement_profitability,
    create_billing_arrangement,
    create_engagement_cost,
    create_invoice,
    delete_engagement_cost,
    get_invoice,
    list_billing_arrangements,
    list_engagement_costs,
    list_invoices_for_engagement,
    list_payments_for_invoice,
    record_payment,
    update_invoice_status,
    void_payment,
)
from app.services.client_delivery import get_client, get_engagement
from app.services.lead_research_permissions import can_view_private_finance
from app.services.workspace_context import require_request_organization_id


router = APIRouter(prefix="/crm/engagements")


def _request_organization_id(db, request: Request) -> int:
    try:
        return require_request_organization_id(request, db=db)
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=403,
            detail="An authorized CRM workspace is required",
        ) from exc


def _require_owner(request: Request) -> None:
    if not can_view_private_finance(request.state.current_user):
        raise HTTPException(status_code=404, detail="Not found")


def _expected_row_version(value: str) -> int | None:
    clean = (value or "").strip()
    if not clean:
        return None
    try:
        parsed = int(clean)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _optional_int(value: str) -> int | None:
    clean = (value or "").strip()
    if not clean:
        return None
    try:
        return int(clean)
    except ValueError:
        return None


def _amount_to_minor_units(value: str) -> int:
    clean = (value or "").strip()
    if not clean:
        raise ValueError("Amount is required.")
    try:
        return round(float(clean) * 100)
    except ValueError:
        raise ValueError("Amount must be a number.") from None


def _redirect_error(exc: Exception, back_to: str) -> RedirectResponse:
    error_key = "stale" if "another session" in str(exc) else "invalid"
    return RedirectResponse(url=f"{back_to}?error={error_key}", status_code=303)


@router.get("/{engagement_id}/billing", response_class=HTMLResponse)
def engagement_billing_page(
    request: Request,
    engagement_id: int,
    notice: str | None = None,
    error: str | None = None,
):
    _require_owner(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        engagement = get_engagement(db, engagement_id, organization_id=organization_id)
        if engagement is None:
            raise HTTPException(status_code=404, detail="Engagement not found")
        client = get_client(db, engagement["client_id"], organization_id=organization_id)

        arrangements = list_billing_arrangements(
            db, engagement_id, organization_id=organization_id
        )
        invoices = list_invoices_for_engagement(
            db, engagement_id, organization_id=organization_id
        )
        invoices_with_payments = [
            {
                **invoice,
                "payments": list_payments_for_invoice(
                    db, invoice["id"], organization_id=organization_id
                ),
            }
            for invoice in invoices
        ]
        costs = list_engagement_costs(db, engagement_id, organization_id=organization_id)
        profitability = compute_engagement_profitability(
            db,
            engagement_id,
            actor=request.state.current_user,
            organization_id=organization_id,
        )

    return templates.TemplateResponse(
        request=request,
        name="engagement_billing.html",
        context={
            "current_user": request.state.current_user,
            "engagement": engagement,
            "client": client,
            "arrangements": arrangements,
            "invoices": invoices_with_payments,
            "costs": costs,
            "profitability": profitability,
            "notice": notice,
            "error": error,
        },
    )


@router.post("/{engagement_id}/billing/arrangements")
def create_arrangement_route(
    request: Request,
    engagement_id: int,
    billing_model: str = Form(...),
    billing_period: str = Form(default="monthly"),
    amount: str = Form(...),
    currency: str = Form(default="PHP"),
    start_date: str = Form(...),
    commission_recipient_user_id: str = Form(default=""),
    commission_rate: str = Form(default=""),
    notes: str = Form(default=""),
):
    _require_owner(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            commission_rate_basis_points = (
                round(float(commission_rate) * 100)
                if commission_rate.strip()
                else None
            )
            create_billing_arrangement(
                db,
                engagement_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                billing_model=billing_model,
                billing_period=billing_period,
                amount_minor_units=_amount_to_minor_units(amount),
                currency=currency,
                start_date=start_date,
                commission_recipient_user_id=_optional_int(
                    commission_recipient_user_id
                ),
                commission_rate_basis_points=commission_rate_basis_points,
                notes=notes,
            )
        except BillingPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/engagements/{engagement_id}/billing?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}/billing?notice=arrangement_created",
        status_code=303,
    )


@router.post("/{engagement_id}/billing/arrangements/{arrangement_id}/cancel")
def cancel_arrangement_route(
    request: Request,
    engagement_id: int,
    arrangement_id: int,
    cancellation_date: str = Form(...),
    row_version: str = Form(default=""),
):
    _require_owner(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            cancel_billing_arrangement(
                db,
                arrangement_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                cancellation_date=cancellation_date,
                expected_row_version=_expected_row_version(row_version),
            )
        except BillingPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError as exc:
            return _redirect_error(exc, f"/crm/engagements/{engagement_id}/billing")
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}/billing?notice=arrangement_cancelled",
        status_code=303,
    )


@router.post("/{engagement_id}/billing/invoices")
def create_invoice_route(
    request: Request,
    engagement_id: int,
    invoice_reference: str = Form(...),
    invoice_date: str = Form(...),
    amount: str = Form(...),
    currency: str = Form(default="PHP"),
    due_date: str = Form(default=""),
    period_start: str = Form(default=""),
    period_end: str = Form(default=""),
    billing_arrangement_id: str = Form(default=""),
    notes: str = Form(default=""),
):
    _require_owner(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            create_invoice(
                db,
                engagement_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                invoice_reference=invoice_reference,
                invoice_date=invoice_date,
                amount_minor_units=_amount_to_minor_units(amount),
                currency=currency,
                billing_arrangement_id=_optional_int(billing_arrangement_id),
                due_date=due_date or None,
                period_start=period_start or None,
                period_end=period_end or None,
                notes=notes,
            )
        except BillingPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/engagements/{engagement_id}/billing?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}/billing?notice=invoice_created",
        status_code=303,
    )


@router.post("/{engagement_id}/billing/invoices/{invoice_id}/status")
def update_invoice_status_route(
    request: Request,
    engagement_id: int,
    invoice_id: int,
    status: str = Form(...),
    row_version: str = Form(default=""),
):
    _require_owner(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            update_invoice_status(
                db,
                invoice_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                status=status,
                expected_row_version=_expected_row_version(row_version),
            )
        except BillingPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError as exc:
            return _redirect_error(exc, f"/crm/engagements/{engagement_id}/billing")
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}/billing?notice=invoice_updated",
        status_code=303,
    )


@router.post("/{engagement_id}/billing/invoices/{invoice_id}/payments")
def record_payment_route(
    request: Request,
    engagement_id: int,
    invoice_id: int,
    amount: str = Form(...),
    currency: str = Form(default="PHP"),
    payment_date: str = Form(...),
    payment_method: str = Form(default=""),
    reference: str = Form(default=""),
    notes: str = Form(default=""),
):
    _require_owner(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            record_payment(
                db,
                invoice_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                amount_minor_units=_amount_to_minor_units(amount),
                currency=currency,
                payment_date=payment_date,
                payment_method=payment_method,
                reference=reference,
                notes=notes,
            )
        except BillingPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/engagements/{engagement_id}/billing?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}/billing?notice=payment_recorded",
        status_code=303,
    )


@router.post("/{engagement_id}/billing/payments/{payment_id}/void")
def void_payment_route(
    request: Request,
    engagement_id: int,
    payment_id: int,
    void_reason: str = Form(...),
):
    _require_owner(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            void_payment(
                db,
                payment_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                void_reason=void_reason,
            )
        except BillingPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/engagements/{engagement_id}/billing?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}/billing?notice=payment_voided",
        status_code=303,
    )


@router.post("/{engagement_id}/billing/costs")
def create_cost_route(
    request: Request,
    engagement_id: int,
    cost_type: str = Form(...),
    description: str = Form(...),
    amount: str = Form(...),
    currency: str = Form(default="PHP"),
    incurred_date: str = Form(...),
    paid_to: str = Form(default=""),
    notes: str = Form(default=""),
):
    _require_owner(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            create_engagement_cost(
                db,
                engagement_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                cost_type=cost_type,
                description=description,
                amount_minor_units=_amount_to_minor_units(amount),
                currency=currency,
                incurred_date=incurred_date,
                paid_to=paid_to,
                notes=notes,
            )
        except BillingPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/engagements/{engagement_id}/billing?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}/billing?notice=cost_created",
        status_code=303,
    )


@router.post("/{engagement_id}/billing/costs/{cost_id}/delete")
def delete_cost_route(
    request: Request,
    engagement_id: int,
    cost_id: int,
):
    _require_owner(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            delete_engagement_cost(
                db,
                cost_id,
                actor=request.state.current_user,
                organization_id=organization_id,
            )
        except BillingPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/engagements/{engagement_id}/billing?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}/billing?notice=cost_deleted",
        status_code=303,
    )
