from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import load_system_state, optional_int, templates

router = APIRouter()


@router.get("/goals", response_class=HTMLResponse)
def goals_page(request: Request):
    with get_db() as db:
        goal_rows = db.execute(
            "SELECT * FROM goals ORDER BY status ASC, priority DESC, id"
        ).fetchall()
        goals_view = []
        for goal in goal_rows:
            goal_dict = dict(goal)
            goal_dict["projects"] = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT p.*,
                           (SELECT COUNT(*) FROM tasks WHERE project_id = p.id AND status != 'completed') AS open_quests,
                           (SELECT COUNT(*) FROM tasks WHERE project_id = p.id AND status = 'completed') AS completed_quests
                    FROM projects p
                    WHERE p.goal_id = ?
                    ORDER BY p.priority DESC, p.id
                    """,
                    (goal["id"],),
                ).fetchall()
            ]
            goal_dict["direct_quests"] = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM tasks
                    WHERE goal_id = ? AND project_id IS NULL
                    ORDER BY status ASC, priority DESC, id
                    """,
                    (goal["id"],),
                ).fetchall()
            ]
            goals_view.append(goal_dict)
        unlinked_projects = db.execute(
            """
            SELECT id, name FROM projects
            WHERE goal_id IS NULL
            ORDER BY priority DESC, id
            """
        ).fetchall()
        system_state = load_system_state(db)
    return templates.TemplateResponse(
        request=request,
        name="goals.html",
        context={
            "goals": goals_view,
            "unlinked_projects": unlinked_projects,
            "system_state": system_state,
        },
    )


@router.post("/goals")
def create_goal(
    title: str = Form(...),
    category: str = Form(default="general"),
    priority: int = Form(default=5),
):
    clean_title = title.strip()
    if not clean_title:
        return RedirectResponse(url="/goals", status_code=303)
    safe_priority = max(1, min(10, priority))
    with get_db() as db:
        db.execute(
            """
            INSERT INTO goals (title, category, priority)
            SELECT ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM goals WHERE title = ?)
            """,
            (clean_title, category.strip() or "general", safe_priority, clean_title),
        )
    return RedirectResponse(url="/goals", status_code=303)


@router.post("/projects/{project_id}/link-goal")
def link_project_goal(project_id: int, goal_id: str = Form(default="")):
    parsed_goal_id = optional_int(goal_id)
    with get_db() as db:
        project = db.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        db.execute(
            "UPDATE projects SET goal_id = ? WHERE id = ?",
            (parsed_goal_id, project_id),
        )
    return RedirectResponse(url="/goals", status_code=303)
