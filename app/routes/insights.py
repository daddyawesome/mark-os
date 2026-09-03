from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.database import get_db
from app.routes.shared import load_system_state, templates
from app.services.insights import build_insights


router = APIRouter()


@router.get("/insights", response_class=HTMLResponse)
def insights_dashboard(request: Request):
    user = request.state.current_user
    with get_db() as db:
        insights = build_insights(db, user)
        system_state = load_system_state(db)
    return templates.TemplateResponse(
        request=request,
        name="insights.html",
        context={
            "current_user": user,
            "system_state": system_state,
            "insights": insights,
        },
    )
