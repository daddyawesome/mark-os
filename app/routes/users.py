from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.database import get_db
from app.routes.shared import load_system_state, templates
from app.services.team_users import create_lead_sourcer


router = APIRouter(prefix="/settings/users")


def _context(
    db,
    *,
    created_user=None,
    error: str | None = None,
) -> dict:
    return {
        "created_user": created_user,
        "error": error,
        "system_state": load_system_state(db),
    }


@router.get("/new", response_class=HTMLResponse)
def new_user_page(request: Request):
    with get_db() as db:
        context = _context(db)
    return templates.TemplateResponse(
        request=request,
        name="user_new.html",
        context=context,
    )


@router.post("/new", response_class=HTMLResponse)
def create_user(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    password_confirmation: str = Form(...),
):
    with get_db() as db:
        try:
            created_user = create_lead_sourcer(
                db,
                username=username,
                display_name=display_name,
                password=password,
                password_confirmation=password_confirmation,
            )
        except ValueError as exc:
            return templates.TemplateResponse(
                request=request,
                name="user_new.html",
                context=_context(db, error=str(exc)),
                status_code=400,
            )

        context = _context(db, created_user=created_user)

    return templates.TemplateResponse(
        request=request,
        name="user_new.html",
        context=context,
        status_code=201,
    )
