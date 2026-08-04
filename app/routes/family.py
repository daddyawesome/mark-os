from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.database import get_db
from app.db.family_workspace import ensure_personal_workspace
from app.routes.shared import load_system_state, templates


router = APIRouter(prefix="/family")


@router.get("/setup", response_class=HTMLResponse)
def family_setup(request: Request):
    user = request.state.current_user
    with get_db() as db:
        result = ensure_personal_workspace(db, int(user["id"]))
        system_state = load_system_state(db, int(user["id"]))

    return templates.TemplateResponse(
        request=request,
        name="family_setup.html",
        context={
            "current_user": user,
            "system_state": system_state,
            "workspace_result": result,
        },
    )
