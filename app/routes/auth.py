from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import (
    authenticate_credentials,
    credentials_configured,
    current_user,
    safe_next_path,
    sign_in,
    sign_out,
)
from app.routes.shared import templates
from app.services.access_control import (
    landing_path_for_user,
    permitted_destination,
)
from app.services.observability import log_security_event


router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    user = current_user(request)
    if user is not None:
        return RedirectResponse(
            url=landing_path_for_user(user),
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "next": safe_next_path(next),
            "error": None,
            "configured": credentials_configured(),
        },
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
):
    requested_destination = safe_next_path(next)
    user = authenticate_credentials(username.strip(), password)

    if user is not None:
        sign_in(request, user)
        log_security_event(
            "authentication_succeeded",
            request,
            user=user,
            status_code=303,
        )
        return RedirectResponse(
            url=permitted_destination(user, requested_destination),
            status_code=303,
        )

    configured = credentials_configured()
    log_security_event(
        "authentication_failed",
        request,
        status_code=401,
        configured=configured,
        username_present=bool(username.strip()),
    )
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "next": requested_destination,
            "error": (
                "Login is not configured yet. Restart MARK OS with "
                "MARK_OS_PASSWORD set so the owner account can be created."
                if not configured
                else "The username or password is incorrect."
            ),
            "configured": configured,
        },
        status_code=401,
    )


@router.post("/logout")
def logout(request: Request):
    sign_out(request)
    return RedirectResponse(url="/login", status_code=303)
