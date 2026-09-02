from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import templates
from app.services.client_delivery import (
    ClientDeliveryStateError,
    cancel_engagement,
    complete_engagement,
    create_engagement,
    create_engagement_item,
    get_client,
    get_client_by_lead,
    get_engagement,
    list_clients,
    list_engagement_items,
    list_engagements_for_client,
    onboard_client_from_lead,
    update_engagement,
    update_engagement_item_status,
    update_engagement_notes,
)
from app.services.client_delivery_permissions import (
    ClientDeliveryPermissionError,
    can_manage_clients,
    can_manage_engagement_items,
    can_update_engagement_notes,
    can_view_engagement,
)
from app.services.leads import get_lead
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


def _redirect_error(exc: Exception, back_to: str) -> RedirectResponse:
    error_key = "stale" if "another session" in str(exc) else "invalid"
    return RedirectResponse(url=f"{back_to}?error={error_key}", status_code=303)


@router.post("/leads/{lead_id}/onboard")
def onboard_lead_as_client(
    request: Request,
    lead_id: int,
    engagement_title: str = Form(...),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            client = onboard_client_from_lead(
                db,
                lead_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                engagement_title=engagement_title,
            )
        except ClientDeliveryPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except (ValueError, ClientDeliveryStateError) as exc:
            return RedirectResponse(
                url=f"/crm/leads/{lead_id}?error=invalid",
                status_code=303,
            )
    return RedirectResponse(url=f"/crm/clients/{client['id']}", status_code=303)


@router.get("/clients", response_class=HTMLResponse)
def list_clients_page(request: Request):
    if not can_manage_clients(request.state.current_user):
        raise HTTPException(status_code=404, detail="Not found")
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        clients = list_clients(db, organization_id=organization_id)
    return templates.TemplateResponse(
        request=request,
        name="clients.html",
        context={"current_user": request.state.current_user, "clients": clients},
    )


def _client_or_404(db, client_id: int, organization_id: int):
    client = get_client(db, client_id, organization_id=organization_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/clients/{client_id}", response_class=HTMLResponse)
def client_detail_page(request: Request, client_id: int):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        client = _client_or_404(db, client_id, organization_id)
        engagements = list_engagements_for_client(
            db, client_id, organization_id=organization_id
        )
        visible_engagements = [
            engagement
            for engagement in engagements
            if can_view_engagement(request.state.current_user, engagement)
        ]
        if not visible_engagements and not can_manage_clients(
            request.state.current_user
        ):
            raise HTTPException(status_code=404, detail="Client not found")

    return templates.TemplateResponse(
        request=request,
        name="client_detail.html",
        context={
            "current_user": request.state.current_user,
            "client": client,
            "engagements": visible_engagements,
            "can_manage": can_manage_clients(request.state.current_user),
        },
    )


@router.post("/clients/{client_id}/engagements")
def create_client_engagement(
    request: Request,
    client_id: int,
    title: str = Form(...),
    delivery_owner_user_id: str = Form(default=""),
    success_criteria: str = Form(default=""),
    deliverables: str = Form(default=""),
    contract_url: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            create_engagement(
                db,
                client_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                title=title,
                delivery_owner_user_id=(
                    int(delivery_owner_user_id)
                    if delivery_owner_user_id.strip()
                    else None
                ),
                success_criteria=success_criteria,
                deliverables=deliverables,
                contract_url=contract_url,
            )
        except ClientDeliveryPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/clients/{client_id}?error=invalid",
                status_code=303,
            )
    return RedirectResponse(url=f"/crm/clients/{client_id}", status_code=303)


def _engagement_or_404(db, request: Request, engagement_id: int, organization_id: int):
    engagement = get_engagement(db, engagement_id, organization_id=organization_id)
    if engagement is None or not can_view_engagement(
        request.state.current_user, engagement
    ):
        raise HTTPException(status_code=404, detail="Engagement not found")
    return engagement


@router.get("/engagements/{engagement_id}", response_class=HTMLResponse)
def engagement_detail_page(
    request: Request,
    engagement_id: int,
    notice: str | None = None,
    error: str | None = None,
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        engagement = _engagement_or_404(db, request, engagement_id, organization_id)
        client = get_client(db, engagement["client_id"], organization_id=organization_id)
        items = list_engagement_items(db, engagement_id, organization_id=organization_id)

    return templates.TemplateResponse(
        request=request,
        name="engagement_detail.html",
        context={
            "current_user": request.state.current_user,
            "engagement": engagement,
            "client": client,
            "items": items,
            "can_manage_scope": can_manage_clients(request.state.current_user),
            "can_update_notes": can_update_engagement_notes(
                request.state.current_user, engagement
            ),
            "can_manage_items": can_manage_engagement_items(
                request.state.current_user, engagement
            ),
            "notice": notice,
            "error": error,
        },
    )


@router.post("/engagements/{engagement_id}/edit")
def edit_engagement(
    request: Request,
    engagement_id: int,
    title: str = Form(...),
    delivery_owner_user_id: str = Form(default=""),
    success_criteria: str = Form(default=""),
    deliverables: str = Form(default=""),
    contract_url: str = Form(default=""),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            update_engagement(
                db,
                engagement_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
                title=title,
                delivery_owner_user_id=(
                    int(delivery_owner_user_id)
                    if delivery_owner_user_id.strip()
                    else None
                ),
                success_criteria=success_criteria,
                deliverables=deliverables,
                contract_url=contract_url,
            )
        except ClientDeliveryPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except (ValueError, ClientDeliveryStateError) as exc:
            return _redirect_error(exc, f"/crm/engagements/{engagement_id}")
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}?notice=updated", status_code=303
    )


@router.post("/engagements/{engagement_id}/notes")
def edit_engagement_notes(
    request: Request,
    engagement_id: int,
    notes: str = Form(default=""),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            update_engagement_notes(
                db,
                engagement_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                notes=notes,
                expected_row_version=_expected_row_version(row_version),
            )
        except ClientDeliveryPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError as exc:
            return _redirect_error(exc, f"/crm/engagements/{engagement_id}")
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}?notice=updated", status_code=303
    )


@router.post("/engagements/{engagement_id}/complete")
def complete_engagement_route(
    request: Request,
    engagement_id: int,
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            complete_engagement(
                db,
                engagement_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except ClientDeliveryPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError as exc:
            return _redirect_error(exc, f"/crm/engagements/{engagement_id}")
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}?notice=completed", status_code=303
    )


@router.post("/engagements/{engagement_id}/cancel")
def cancel_engagement_route(
    request: Request,
    engagement_id: int,
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            cancel_engagement(
                db,
                engagement_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                expected_row_version=_expected_row_version(row_version),
            )
        except ClientDeliveryPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError as exc:
            return _redirect_error(exc, f"/crm/engagements/{engagement_id}")
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}?notice=cancelled", status_code=303
    )


@router.post("/engagements/{engagement_id}/items")
def create_engagement_item_route(
    request: Request,
    engagement_id: int,
    item_type: str = Form(...),
    title: str = Form(...),
    description: str = Form(default=""),
    due_date: str = Form(default=""),
    assigned_to_user_id: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            create_engagement_item(
                db,
                engagement_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                item_type=item_type,
                title=title,
                description=description,
                due_date=due_date or None,
                assigned_to_user_id=(
                    int(assigned_to_user_id)
                    if assigned_to_user_id.strip()
                    else None
                ),
            )
        except ClientDeliveryPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError:
            return RedirectResponse(
                url=f"/crm/engagements/{engagement_id}?error=invalid",
                status_code=303,
            )
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}?notice=item_added", status_code=303
    )


@router.post("/engagements/{engagement_id}/items/{item_id}/status")
def update_engagement_item_status_route(
    request: Request,
    engagement_id: int,
    item_id: int,
    status: str = Form(...),
    row_version: str = Form(default=""),
):
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            update_engagement_item_status(
                db,
                item_id,
                actor=request.state.current_user,
                organization_id=organization_id,
                status=status,
                expected_row_version=_expected_row_version(row_version),
            )
        except ClientDeliveryPermissionError:
            raise HTTPException(status_code=404, detail="Not found")
        except ValueError as exc:
            return _redirect_error(exc, f"/crm/engagements/{engagement_id}")
    return RedirectResponse(
        url=f"/crm/engagements/{engagement_id}?notice=item_updated", status_code=303
    )
