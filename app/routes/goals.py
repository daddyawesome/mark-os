from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import load_system_state, optional_int, templates
from app.services.personal_scope import request_user_id


router = APIRouter()


@router.get("/goals", response_class=HTMLResponse)
def goals_page(request: Request):
    user_id = request_user_id(request)

    with get_db() as db:
        goal_rows = db.execute(
            """
            SELECT *
            FROM goals
            WHERE user_id = ?
            ORDER BY status ASC, priority DESC, id
            """,
            (user_id,),
        ).fetchall()

        goals_view = []
        for goal in goal_rows:
            goal_dict = dict(goal)
            goal_dict["projects"] = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT
                        p.*,
                        (
                            SELECT COUNT(*)
                            FROM tasks
                            WHERE user_id = ?
                              AND project_id = p.id
                              AND status NOT IN (
                                  'completed',
                                  'abandoned',
                                  'closed'
                              )
                        ) AS open_quests,
                        (
                            SELECT COUNT(*)
                            FROM tasks
                            WHERE user_id = ?
                              AND project_id = p.id
                              AND status = 'completed'
                        ) AS completed_quests
                    FROM projects AS p
                    WHERE p.user_id = ? AND p.goal_id = ?
                    ORDER BY p.priority DESC, p.id
                    """,
                    (
                        user_id,
                        user_id,
                        user_id,
                        goal["id"],
                    ),
                ).fetchall()
            ]
            goal_dict["direct_quests"] = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT *
                    FROM tasks
                    WHERE user_id = ?
                      AND goal_id = ?
                      AND project_id IS NULL
                    ORDER BY status ASC, priority DESC, id
                    """,
                    (user_id, goal["id"]),
                ).fetchall()
            ]
            goals_view.append(goal_dict)

        unlinked_projects = db.execute(
            """
            SELECT id, name
            FROM projects
            WHERE user_id = ? AND goal_id IS NULL
            ORDER BY priority DESC, id
            """,
            (user_id,),
        ).fetchall()
        system_state = load_system_state(db, user_id)

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
    request: Request,
    title: str = Form(...),
    category: str = Form(default="general"),
    priority: int = Form(default=5),
):
    clean_title = title.strip()
    if not clean_title:
        return RedirectResponse(url="/goals", status_code=303)

    user_id = request_user_id(request)
    safe_priority = max(1, min(10, priority))

    with get_db() as db:
        db.execute(
            """
            INSERT INTO goals (user_id, title, category, priority)
            SELECT ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1
                FROM goals
                WHERE user_id = ? AND title = ?
            )
            """,
            (
                user_id,
                clean_title,
                category.strip() or "general",
                safe_priority,
                user_id,
                clean_title,
            ),
        )

    return RedirectResponse(url="/goals", status_code=303)


@router.post("/projects/{project_id}/link-goal")
def link_project_goal(
    request: Request,
    project_id: int,
    goal_id: str = Form(default=""),
):
    user_id = request_user_id(request)
    parsed_goal_id = optional_int(goal_id)

    with get_db() as db:
        project = db.execute(
            """
            SELECT id
            FROM projects
            WHERE id = ? AND user_id = ?
            """,
            (project_id, user_id),
        ).fetchone()
        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        if parsed_goal_id is not None:
            goal = db.execute(
                """
                SELECT id
                FROM goals
                WHERE id = ? AND user_id = ?
                """,
                (parsed_goal_id, user_id),
            ).fetchone()
            if not goal:
                raise HTTPException(
                    status_code=404,
                    detail="Goal not found",
                )

        db.execute(
            """
            UPDATE projects
            SET goal_id = ?
            WHERE id = ? AND user_id = ?
            """,
            (parsed_goal_id, project_id, user_id),
        )

    return RedirectResponse(url="/goals", status_code=303)
