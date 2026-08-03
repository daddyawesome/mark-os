from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import (
    credentials_configured,
    is_authenticated,
    safe_next_path,
    sign_in,
    sign_out,
    verify_credentials,
)
from app.routes.shared import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
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
    destination = safe_next_path(next)
    if verify_credentials(username.strip(), password):
        sign_in(request)
        return RedirectResponse(url=destination, status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "next": destination,
            "error": (
                "Login is not configured yet. Set MARK_OS_PASSWORD in Railway."
                if not credentials_configured()
                else "The username or password is incorrect."
            ),
            "configured": credentials_configured(),
        },
        status_code=401,
    )


@router.post("/logout")
def logout(request: Request):
    sign_out(request)
    return RedirectResponse(url="/login", status_code=303)
