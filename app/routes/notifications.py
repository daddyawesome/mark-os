from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.database import get_db
from app.routes.shared import load_system_state, templates
from app.services.notifications import build_notifications


router = APIRouter()


@router.get("/notifications", response_class=HTMLResponse)
def notification_center(request: Request):
    user = request.state.current_user
    with get_db() as db:
        notifications = build_notifications(db, user)
        system_state = load_system_state(db)
    return templates.TemplateResponse(
        request=request,
        name="notifications.html",
        context={
            "current_user": user,
            "system_state": system_state,
            "notifications": notifications,
        },
    )
