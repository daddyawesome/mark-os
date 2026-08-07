from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from app.auth import safe_next_path
from app.database import get_db
from app.services.access_control import is_owner
from app.services.workspace_context import select_current_workspace


router = APIRouter()


@router.post("/workspace/select")
def select_workspace(
    request: Request,
    organization_id: int = Form(...),
    next: str = Form(default="/crm"),
):
    user = request.state.current_user
    if not is_owner(user):
        return PlainTextResponse("Forbidden", status_code=403)

    with get_db() as db:
        try:
            select_current_workspace(
                db,
                request.session,
                user,
                organization_id,
            )
        except (PermissionError, ValueError):
            return PlainTextResponse("Forbidden", status_code=403)

    destination = safe_next_path(next)
    if not (
        destination == "/crm"
        or destination.startswith("/crm/")
        or destination == "/relationship-manager"
        or destination == "/pendang"
    ):
        destination = "/crm"
    return RedirectResponse(destination, status_code=303)
