from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import (
    bounded_int,
    load_system_state,
    optional_int,
    templates,
)
from app.services.gamification import (
    XP_BY_DIFFICULTY,
    normalize_difficulty,
    xp_for_difficulty,
)
from app.services.quests import (
    complete_quest as complete_quest_transaction,
    normalize_minutes,
    set_quest_status,
    update_quest_progress,
)

router = APIRouter()


@router.get("/quests", response_class=HTMLResponse)
def quests(request: Request):
    with get_db() as db:
        rows = db.execute(
            """
            SELECT
                t.*,
                p.name AS project_name,
                COALESCE(gt.title, gp.title) AS goal_title,
                COALESCE(SUM(COALESCE(qu.session_minutes, qu.actual_minutes, 0)), 0) AS total_session_minutes
            FROM tasks t
            LEFT JOIN projects p ON p.id = t.project_id
            LEFT JOIN goals gt ON gt.id = t.goal_id
            LEFT JOIN goals gp ON gp.id = p.goal_id
            LEFT JOIN quest_updates qu ON qu.task_id = t.id
            GROUP BY t.id
            ORDER BY CASE t.status
                        WHEN 'active' THEN 0
                        WHEN 'blocked' THEN 1
                        WHEN 'backlog' THEN 2
                        WHEN 'completed' THEN 3
                        WHEN 'abandoned' THEN 4
                        ELSE 5
                     END,
                     t.priority DESC,
                     t.id DESC
            """
        ).fetchall()
        projects = db.execute(
            """
            SELECT id, name FROM projects
            WHERE status = 'active'
            ORDER BY priority DESC, id
            """
        ).fetchall()
        goals = db.execute(
            """
            SELECT id, title FROM goals
            WHERE status = 'active'
            ORDER BY priority DESC, id
            """
        ).fetchall()
        system_state = load_system_state(db)

    return templates.TemplateResponse(
        request=request,
        name="quests.html",
        context={
            "quests": rows,
            "projects": projects,
            "goals": goals,
            "system_state": system_state,
            "xp_rewards": XP_BY_DIFFICULTY,
        },
    )


@router.post("/quests")
def create_quest(
    title: str = Form(...),
    description: str = Form(default=""),
    project_id: str = Form(default=""),
    goal_id: str = Form(default=""),
    difficulty: str = Form(default="normal"),
    priority: int = Form(default=5),
    estimated_minutes: str = Form(default=""),
    energy_required: int = Form(default=3),
    due_date: str = Form(default=""),
    why: str = Form(default=""),
):
    clean_title = title.strip()
    if not clean_title:
        return RedirectResponse(url="/quests", status_code=303)

    clean_difficulty = normalize_difficulty(difficulty)
    xp_reward = xp_for_difficulty(clean_difficulty)
    parsed_project_id = optional_int(project_id)
    parsed_goal_id = optional_int(goal_id) if not parsed_project_id else None
    parsed_minutes = normalize_minutes(optional_int(estimated_minutes))
    safe_priority = bounded_int(priority, default=5, low=1, high=10)
    safe_energy = bounded_int(energy_required, default=3, low=1, high=5)

    with get_db() as db:
        db.execute(
            """
            INSERT INTO tasks
            (project_id, goal_id, title, description, status, priority, estimated_minutes,
             energy_required, due_date, difficulty, xp_reward, progress, quest_source, why)
            VALUES (?, ?, ?, ?, 'backlog', ?, ?, ?, ?, ?, ?, 0, 'manual', ?)
            """,
            (
                parsed_project_id,
                parsed_goal_id,
                clean_title,
                description.strip(),
                safe_priority,
                parsed_minutes,
                safe_energy,
                due_date.strip() or None,
                clean_difficulty,
                xp_reward,
                why.strip(),
            ),
        )

    return RedirectResponse(url="/quests", status_code=303)


@router.get("/quests/{quest_id}", response_class=HTMLResponse)
def quest_detail(request: Request, quest_id: int):
    with get_db() as db:
        quest = db.execute(
            """
            SELECT
                t.*,
                p.name AS project_name,
                COALESCE(gt.title, gp.title) AS goal_title,
                COALESCE(SUM(COALESCE(qu.session_minutes, qu.actual_minutes, 0)), 0) AS total_session_minutes
            FROM tasks t
            LEFT JOIN projects p ON p.id = t.project_id
            LEFT JOIN goals gt ON gt.id = t.goal_id
            LEFT JOIN goals gp ON gp.id = p.goal_id
            LEFT JOIN quest_updates qu ON qu.task_id = t.id
            WHERE t.id = ?
            GROUP BY t.id
            """,
            (quest_id,),
        ).fetchone()
        if not quest:
            raise HTTPException(status_code=404, detail="Quest not found")

        updates = db.execute(
            """
            SELECT * FROM quest_updates
            WHERE task_id = ?
            ORDER BY id DESC
            """,
            (quest_id,),
        ).fetchall()
        xp_award = db.execute(
            "SELECT * FROM xp_ledger WHERE task_id = ?", (quest_id,)
        ).fetchone()
        system_state = load_system_state(db)

    return templates.TemplateResponse(
        request=request,
        name="quest_detail.html",
        context={
            "quest": quest,
            "updates": updates,
            "xp_award": xp_award,
            "system_state": system_state,
            "completed_now": request.query_params.get("completed") == "1",
            "duplicate_award": request.query_params.get("duplicate") == "1",
            "result_required": request.query_params.get("error") == "result_required",
            "levels_gained": optional_int(request.query_params.get("levels")) or 0,
        },
    )


@router.post("/quests/{quest_id}/start")
def start_quest(quest_id: int):
    with get_db() as db:
        try:
            set_quest_status(db, quest_id=quest_id, status="active")
        except ValueError:
            raise HTTPException(status_code=404, detail="Quest not found")
    return RedirectResponse(url=f"/quests/{quest_id}", status_code=303)


@router.post("/quests/{quest_id}/block")
def block_quest(
    quest_id: int,
    blocker_reason: str = Form(default=""),
    note: str = Form(default=""),
):
    with get_db() as db:
        try:
            set_quest_status(
                db,
                quest_id=quest_id,
                status="blocked",
                note=note,
                blocker_reason=blocker_reason,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Quest not found")
    return RedirectResponse(url=f"/quests/{quest_id}", status_code=303)


@router.post("/quests/{quest_id}/unblock")
def unblock_quest(quest_id: int):
    with get_db() as db:
        try:
            set_quest_status(
                db,
                quest_id=quest_id,
                status="active",
                note="Quest unblocked.",
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Quest not found")
    return RedirectResponse(url=f"/quests/{quest_id}", status_code=303)


@router.post("/quests/{quest_id}/abandon")
def abandon_quest(quest_id: int, note: str = Form(default="")):
    with get_db() as db:
        try:
            set_quest_status(db, quest_id=quest_id, status="abandoned", note=note)
        except ValueError:
            raise HTTPException(status_code=404, detail="Quest not found")
    return RedirectResponse(url=f"/quests/{quest_id}", status_code=303)


@router.post("/quests/{quest_id}/update")
def update_quest(
    quest_id: int,
    note: str = Form(default=""),
    progress: int = Form(default=0),
    session_minutes: str = Form(default=""),
):
    parsed_minutes = normalize_minutes(optional_int(session_minutes))
    with get_db() as db:
        try:
            update_quest_progress(
                db,
                quest_id=quest_id,
                note=note,
                progress=progress,
                session_minutes=parsed_minutes,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Quest not found")
    return RedirectResponse(url=f"/quests/{quest_id}", status_code=303)


@router.post("/quests/{quest_id}/complete")
def complete_quest(
    quest_id: int,
    result_notes: str = Form(default=""),
    evidence: str = Form(default=""),
    session_minutes: str = Form(default=""),
):
    if not result_notes.strip():
        return RedirectResponse(
            url=f"/quests/{quest_id}?error=result_required",
            status_code=303,
        )

    parsed_minutes = normalize_minutes(optional_int(session_minutes))
    with get_db() as db:
        try:
            result = complete_quest_transaction(
                db,
                quest_id=quest_id,
                result_notes=result_notes,
                evidence=evidence,
                session_minutes=parsed_minutes,
            )
        except ValueError as exc:
            if str(exc) == "Quest not found":
                raise HTTPException(status_code=404, detail="Quest not found")
            return RedirectResponse(
                url=f"/quests/{quest_id}?error=result_required",
                status_code=303,
            )

    duplicate = "1" if result.duplicate_award else "0"
    return RedirectResponse(
        url=(
            f"/quests/{quest_id}?completed=1&levels={result.levels_gained}"
            f"&duplicate={duplicate}"
        ),
        status_code=303,
    )
