from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.database import get_db
from app.routes.shared import templates
from app.services.access_control import has_crm_owner_authority
from app.services.lead_sourcing_effort import (
    EffortPermissionError,
    compute_lead_sourcing_effort,
    list_staff_for_effort_report,
)
from app.services.workspace_context import require_request_organization_id


router = APIRouter(prefix="/crm/effort")

MANILA_TIMEZONE = ZoneInfo("Asia/Manila")


def _request_organization_id(db, request: Request) -> int:
    try:
        return require_request_organization_id(request, db=db)
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=403,
            detail="An authorized CRM workspace is required",
        ) from exc


def _default_period() -> tuple[str, str]:
    today = datetime.now(timezone.utc).astimezone(MANILA_TIMEZONE).date()
    period_start = date(today.year, today.month, 1)
    return period_start.isoformat(), today.isoformat()


@router.get("", response_class=HTMLResponse)
def lead_sourcing_effort_page(
    request: Request,
    user_id: int | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    error: str | None = None,
):
    current_user = request.state.current_user
    if current_user["role"] not in {"owner", "lead_sourcer", "relationship_manager"}:
        raise HTTPException(status_code=404, detail="Not found")

    can_manage = has_crm_owner_authority(current_user)
    default_start, default_end = _default_period()
    safe_period_start = period_start or default_start
    safe_period_end = period_end or default_end
    target_user_id = user_id if (user_id and can_manage) else int(current_user["id"])

    with get_db() as db:
        organization_id = _request_organization_id(db, request)
        staff = list_staff_for_effort_report(
            db,
            organization_id=organization_id,
        ) if can_manage else []

        summary = None
        summary_error = error
        try:
            summary = compute_lead_sourcing_effort(
                db,
                actor=current_user,
                user_id=target_user_id,
                organization_id=organization_id,
                period_start=safe_period_start,
                period_end=safe_period_end,
            )
        except (EffortPermissionError, ValueError) as exc:
            summary_error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="lead_sourcing_effort.html",
        context={
            "current_user": current_user,
            "can_manage": can_manage,
            "staff": staff,
            "summary": summary,
            "error": summary_error,
            "selected_user_id": target_user_id,
            "period_start": safe_period_start,
            "period_end": safe_period_end,
        },
    )
