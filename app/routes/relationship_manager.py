from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import templates
from app.services.access_control import is_relationship_manager
from app.services.relationship_manager import (
    load_relationship_manager_dashboard,
)


router = APIRouter()


@router.get(
    "/relationship-manager",
    response_class=HTMLResponse,
)
def relationship_manager_home(request: Request):
    user = request.state.current_user
    if not is_relationship_manager(user):
        return RedirectResponse(
            url="/crm",
            status_code=303,
        )

    with get_db() as db:
        dashboard = load_relationship_manager_dashboard(
            db,
            user,
        )
        context = {
            "current_user": user,
            "system_state": None,
            "playbook": dashboard["playbook"],
            "metric_cards": dashboard["metric_cards"],
            "relationship_queues": dashboard["queues"],
            "error": (
                "That action is not available to the Relationship Manager."
                if request.query_params.get("error") == "forbidden"
                else None
            ),
        }

    return templates.TemplateResponse(
        request=request,
        name="relationship_manager.html",
        context=context,
    )
