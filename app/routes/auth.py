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
from app.database import get_db
from app.routes.shared import templates
from app.services.access_control import (
    landing_path_for_user,
    permitted_destination,
)
from app.services.observability import log_security_event
from app.services.team_users import change_own_password


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
        if bool(user.get("must_change_password")):
            return RedirectResponse(
                url="/account/password",
                status_code=303,
            )
        resolved_user = current_user(request) or user
        return RedirectResponse(
            url=permitted_destination(
                resolved_user,
                requested_destination,
            ),
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

@router.get("/account/password", response_class=HTMLResponse)
def account_password_page(
    request: Request,
    message: str | None = None,
    error: str | None = None,
):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="account_password.html",
        context={
            "current_user": user,
            "message": message,
            "error": error,
            "required_change": bool(user.get("must_change_password")),
        },
    )


@router.post("/account/password")
def account_password_submit(
    request: Request,
    current_password: str = Form(...),
    password: str = Form(...),
    password_confirmation: str = Form(...),
):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    with get_db() as db:
        try:
            updated = change_own_password(
                db,
                user_id=int(user["id"]),
                current_password=current_password,
                password=password,
                password_confirmation=password_confirmation,
            )
        except ValueError as exc:
            return templates.TemplateResponse(
                request=request,
                name="account_password.html",
                context={
                    "current_user": user,
                    "message": None,
                    "error": str(exc),
                    "required_change": bool(user.get("must_change_password")),
                },
                status_code=400,
            )

    sign_in(request, updated)
    resolved_user = current_user(request) or updated
    return RedirectResponse(
        url=landing_path_for_user(resolved_user),
        status_code=303,
    )
