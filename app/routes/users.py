from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import load_system_state, templates
from app.services.team_users import (
    create_managed_user,
    get_user_for_management,
    list_users_with_stats,
    reset_user_password,
    set_user_active,
)


router = APIRouter(prefix="/settings/users")


def _redirect(
    path: str,
    *,
    message: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    query = {
        key: value
        for key, value in {
            "message": message,
            "error": error,
        }.items()
        if value
    }
    destination = f"{path}?{urlencode(query)}" if query else path
    return RedirectResponse(url=destination, status_code=303)


def _shared_context(db, request: Request) -> dict:
    return {
        "system_state": load_system_state(db),
        "current_user": request.state.current_user,
    }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def users_page(
    request: Request,
    message: str | None = None,
    error: str | None = None,
    role: str | None = None,
):
    selected_role = (role or "").strip().casefold()
    if selected_role not in {
        "member",
        "lead_sourcer",
        "relationship_manager",
    }:
        selected_role = ""

    with get_db() as db:
        users = list_users_with_stats(db)
        if selected_role:
            users = [
                user
                for user in users
                if user["role"] == selected_role
            ]

        context = {
            **_shared_context(db, request),
            "users": users,
            "selected_role": selected_role,
            "message": message,
            "error": error,
        }

    return templates.TemplateResponse(
        request=request,
        name="users.html",
        context=context,
    )


@router.get("/new", response_class=HTMLResponse)
def new_user_page(
    request: Request,
    message: str | None = None,
    error: str | None = None,
):
    with get_db() as db:
        context = {
            **_shared_context(db, request),
            "message": message,
            "error": error,
        }
    return templates.TemplateResponse(
        request=request,
        name="user_new.html",
        context=context,
    )


@router.post("/new")
def create_user(
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    password_confirmation: str = Form(...),
    role: str = Form(default="lead_sourcer"),
):
    with get_db() as db:
        try:
            created_user = create_managed_user(
                db,
                username=username,
                display_name=display_name,
                password=password,
                password_confirmation=password_confirmation,
                role=role,
            )
        except ValueError as exc:
            return _redirect("/settings/users/new", error=str(exc))

    role_label = created_user["role"].replace("_", " ").title()
    return _redirect(
        f"/settings/users/{created_user['id']}",
        message=(
            f"{role_label} account created for "
            f"{created_user['display_name']}."
        ),
    )


@router.get("/{user_id}", response_class=HTMLResponse)
def manage_user_page(
    request: Request,
    user_id: int,
    message: str | None = None,
    error: str | None = None,
):
    with get_db() as db:
        managed_user = get_user_for_management(db, user_id)
        if managed_user is None:
            return _redirect(
                "/settings/users",
                error="User not found.",
            )

        context = {
            **_shared_context(db, request),
            "managed_user": managed_user,
            "message": message,
            "error": error,
        }

    return templates.TemplateResponse(
        request=request,
        name="user_manage.html",
        context=context,
    )


@router.post("/{user_id}/status")
def update_user_status(
    request: Request,
    user_id: int,
    action: str = Form(...),
):
    normalized_action = action.strip().casefold()
    if normalized_action not in {"activate", "deactivate"}:
        return _redirect(
            f"/settings/users/{user_id}",
            error="Unsupported account action.",
        )

    acting_user = request.state.current_user
    with get_db() as db:
        try:
            updated = set_user_active(
                db,
                target_user_id=user_id,
                acting_user_id=int(acting_user["id"]),
                active=normalized_action == "activate",
            )
        except ValueError as exc:
            return _redirect(
                f"/settings/users/{user_id}",
                error=str(exc),
            )

    state_label = "activated" if updated["active"] else "deactivated"
    return _redirect(
        f"/settings/users/{user_id}",
        message=(
            f"{updated['display_name']} was {state_label}. "
            "Existing sessions were revoked."
        ),
    )


@router.post("/{user_id}/password")
def update_user_password(
    user_id: int,
    password: str = Form(...),
    password_confirmation: str = Form(...),
):
    with get_db() as db:
        try:
            updated = reset_user_password(
                db,
                target_user_id=user_id,
                password=password,
                password_confirmation=password_confirmation,
            )
        except ValueError as exc:
            return _redirect(
                f"/settings/users/{user_id}",
                error=str(exc),
            )

    return _redirect(
        f"/settings/users/{user_id}",
        message=(
            f"Password reset for {updated['display_name']}. "
            "Existing sessions were revoked."
        ),
    )
