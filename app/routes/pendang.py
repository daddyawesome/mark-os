from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import templates
from app.services.pendang_company import (
    ITEM_STATUSES,
    ITEM_TYPE_LABELS,
    SECTIONS,
    PendangCompanyConflictError,
    PendangCompanyNotFoundError,
    PendangCompanyPermissionError,
    archive_knowledge_item,
    create_knowledge_item,
    load_company_home,
    update_company_profile,
    update_knowledge_item,
)


router = APIRouter()


def _redirect(*, notice: str | None = None, error: str | None = None):
    query = {}
    if notice:
        query["notice"] = notice
    if error:
        query["error"] = error
    suffix = f"?{urlencode(query)}" if query else ""
    return RedirectResponse(url=f"/pendang{suffix}", status_code=303)


def _actor(request: Request):
    actor = request.state.current_user
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return actor


def _handle_mutation_error(exc: Exception):
    if isinstance(exc, PendangCompanyPermissionError):
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    if isinstance(exc, PendangCompanyNotFoundError):
        raise HTTPException(status_code=404, detail="Not found") from exc
    if isinstance(exc, PendangCompanyConflictError):
        return _redirect(error=str(exc))
    if isinstance(exc, ValueError):
        return _redirect(error=str(exc))
    raise exc


@router.get("/pendang", response_class=HTMLResponse)
def pendang_home(
    request: Request,
    notice: str | None = None,
    error: str | None = None,
):
    with get_db() as db:
        try:
            company = load_company_home(db, _actor(request))
        except PendangCompanyPermissionError as exc:
            raise HTTPException(status_code=403, detail="Forbidden") from exc

    return templates.TemplateResponse(
        request=request,
        name="pendang_company.html",
        context={
            "company": company,
            "current_user": request.state.current_user,
            "current_workspace": request.state.current_workspace,
            "can_manage": bool(company["can_manage"]),
            "sections": SECTIONS,
            "item_type_labels": ITEM_TYPE_LABELS,
            "item_statuses": ITEM_STATUSES,
            "notice": notice,
            "error": error,
        },
    )


@router.post("/pendang/profile")
def update_pendang_profile(
    request: Request,
    founder_plan: str = Form(...),
    about_company: str = Form(default=""),
    company_cv: str = Form(default=""),
    row_version: int = Form(...),
):
    try:
        with get_db() as db:
            update_company_profile(
                db,
                _actor(request),
                founder_plan=founder_plan,
                about_company=about_company,
                company_cv=company_cv,
                expected_row_version=row_version,
            )
    except Exception as exc:
        handled = _handle_mutation_error(exc)
        if handled is not None:
            return handled
        raise
    return _redirect(notice="company-profile-updated")


@router.post("/pendang/items")
def create_pendang_item(
    request: Request,
    item_type: str = Form(...),
    title: str = Form(...),
    subtitle: str = Form(default=""),
    body: str = Form(default=""),
    details: str = Form(default=""),
    reference_url: str = Form(default=""),
    scheduled_for: str = Form(default=""),
    status: str = Form(default="draft"),
):
    try:
        with get_db() as db:
            create_knowledge_item(
                db,
                _actor(request),
                item_type=item_type,
                title=title,
                subtitle=subtitle,
                body=body,
                details=details,
                reference_url=reference_url,
                scheduled_for=scheduled_for,
                status=status,
            )
    except Exception as exc:
        handled = _handle_mutation_error(exc)
        if handled is not None:
            return handled
        raise
    return _redirect(notice="company-entry-added")


@router.post("/pendang/items/{item_id}/edit")
def edit_pendang_item(
    request: Request,
    item_id: int,
    title: str = Form(...),
    subtitle: str = Form(default=""),
    body: str = Form(default=""),
    details: str = Form(default=""),
    reference_url: str = Form(default=""),
    scheduled_for: str = Form(default=""),
    status: str = Form(default="draft"),
    row_version: int = Form(...),
):
    try:
        with get_db() as db:
            update_knowledge_item(
                db,
                _actor(request),
                item_id,
                title=title,
                subtitle=subtitle,
                body=body,
                details=details,
                reference_url=reference_url,
                scheduled_for=scheduled_for,
                status=status,
                expected_row_version=row_version,
            )
    except Exception as exc:
        handled = _handle_mutation_error(exc)
        if handled is not None:
            return handled
        raise
    return _redirect(notice="company-entry-updated")


@router.post("/pendang/items/{item_id}/archive")
def archive_pendang_item(
    request: Request,
    item_id: int,
    row_version: int = Form(...),
):
    try:
        with get_db() as db:
            archive_knowledge_item(
                db,
                _actor(request),
                item_id,
                expected_row_version=row_version,
            )
    except Exception as exc:
        handled = _handle_mutation_error(exc)
        if handled is not None:
            return handled
        raise
    return _redirect(notice="company-entry-archived")
