from __future__ import annotations

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import templates
from app.services.access_control import has_crm_owner_authority
from app.services.webhook_intake import (
    WebhookAuthenticationError,
    WebhookIntakeError,
    authenticate_webhook_token,
    create_webhook_token,
    ingest_lead_payload,
    list_webhook_tokens,
    revoke_webhook_token,
)
from app.services.workspace_context import require_request_organization_id


router = APIRouter()
admin_router = APIRouter(prefix="/crm/webhooks")

MAX_INTAKE_BODY_BYTES = 50_000


@router.post("/api/leads/intake")
async def intake_lead_webhook(request: Request):
    """Authenticated, organization-scoped inbound lead intake.

    Never approves research, outreach, pipeline movement, proposals, or any
    financial action. A successfully ingested lead enters at exactly the
    same draft/new state a manually created lead does.
    """
    authorization = request.headers.get("authorization", "")
    scheme, _, raw_token = authorization.partition(" ")
    if scheme.strip().casefold() != "bearer" or not raw_token.strip():
        return JSONResponse(
            status_code=401,
            content={"error": "A Bearer token is required."},
        )

    body = await request.body()
    if len(body) > MAX_INTAKE_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": "Payload too large."},
        )

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse(
            status_code=400,
            content={"error": "Payload must be valid JSON."},
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={"error": "Payload must be a JSON object."},
        )

    with get_db() as db:
        try:
            token_record = authenticate_webhook_token(db, raw_token.strip())
        except WebhookAuthenticationError:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or revoked webhook token."},
            )

        try:
            result = ingest_lead_payload(
                db,
                token_record=token_record,
                payload=payload,
            )
        except WebhookIntakeError as exc:
            return JSONResponse(
                status_code=422,
                content={"error": str(exc)},
            )

    status_code = 201 if result.created else 200
    return JSONResponse(
        status_code=status_code,
        content={"outcome": result.outcome, "lead_id": result.lead_id},
    )


def _request_organization_id(db, request: Request) -> int:
    try:
        return require_request_organization_id(request, db=db)
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=403,
            detail="An authorized CRM workspace is required",
        ) from exc


def _require_owner_authority(request: Request) -> None:
    if not has_crm_owner_authority(request.state.current_user):
        raise HTTPException(status_code=404, detail="Not found")


@admin_router.get("", response_class=HTMLResponse)
def list_webhook_tokens_page(
    request: Request,
    notice: str | None = None,
    issued_token: str | None = None,
):
    _require_owner_authority(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        tokens = list_webhook_tokens(db, organization_id=organization_id)

    return templates.TemplateResponse(
        request=request,
        name="webhook_tokens.html",
        context={
            "current_user": request.state.current_user,
            "tokens": tokens,
            "notice": notice,
            "issued_token": issued_token,
        },
    )


@admin_router.post("")
def create_webhook_token_route(
    request: Request,
    source_name: str = Form(...),
):
    _require_owner_authority(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            issued = create_webhook_token(
                db,
                actor=request.state.current_user,
                organization_id=organization_id,
                source_name=source_name,
            )
        except (PermissionError, ValueError):
            return RedirectResponse(
                url="/crm/webhooks?notice=invalid",
                status_code=303,
            )

    return RedirectResponse(
        url=f"/crm/webhooks?notice=created&issued_token={issued.token}",
        status_code=303,
    )


@admin_router.post("/{token_id}/revoke")
def revoke_webhook_token_route(
    request: Request,
    token_id: int,
):
    _require_owner_authority(request)
    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        try:
            revoke_webhook_token(
                db,
                token_id,
                actor=request.state.current_user,
                organization_id=organization_id,
            )
        except (PermissionError, ValueError):
            return RedirectResponse(
                url="/crm/webhooks?notice=invalid",
                status_code=303,
            )

    return RedirectResponse(url="/crm/webhooks?notice=revoked", status_code=303)
