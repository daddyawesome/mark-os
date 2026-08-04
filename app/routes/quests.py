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
from app.services.personal_scope import request_user_id
from app.services.quests import (
    complete_quest as complete_quest_transaction,
    normalize_minutes,
    set_quest_status,
    update_quest_progress,
)


router = APIRouter()


def _client_hunting_destination(
    db,
    quest_id: int,
    user_id: int,
) -> str | None:
    lead = db.execute(
        """
        SELECT l.id, l.deleted_at
        FROM leads AS l
        JOIN tasks AS t ON t.id = l.quest_id
        WHERE l.quest_id = ? AND t.user_id = ?
        """,
        (quest_id, user_id),
    ).fetchone()
    if not lead:
        return None
    if lead["deleted_at"] is not None:
        return "/crm"
    return f"/crm/leads/{lead['id']}"


@router.get("/quests", response_class=HTMLResponse)
def quests(request: Request):
    user_id = request_user_id(request)

    with get_db() as db:
        rows = db.execute(
            """
            SELECT
                t.*,
                p.name AS project_name,
                COALESCE(gt.title, gp.title) AS goal_title,
                l.id AS lead_id,
                l.company AS lead_company,
                l.pipeline_status AS lead_pipeline_status,
                l.next_action AS lead_next_action,
                l.next_action_due_date AS lead_next_action_due_date,
                l.deleted_at AS lead_deleted_at,
                COALESCE(
                    SUM(
                        COALESCE(
                            qu.session_minutes,
                            qu.actual_minutes,
                            0
                        )
                    ),
                    0
                ) AS total_session_minutes
            FROM tasks AS t
            LEFT JOIN projects AS p
              ON p.id = t.project_id
             AND p.user_id = t.user_id
            LEFT JOIN goals AS gt
              ON gt.id = t.goal_id
             AND gt.user_id = t.user_id
            LEFT JOIN goals AS gp
              ON gp.id = p.goal_id
             AND gp.user_id = t.user_id
            LEFT JOIN leads AS l
              ON l.quest_id = t.id
            LEFT JOIN quest_updates AS qu
              ON qu.task_id = t.id
             AND qu.user_id = t.user_id
            WHERE t.user_id = ?
            GROUP BY t.id
            ORDER BY
                CASE t.status
                    WHEN 'active' THEN 0
                    WHEN 'blocked' THEN 1
                    WHEN 'backlog' THEN 2
                    WHEN 'completed' THEN 3
                    WHEN 'closed' THEN 4
                    WHEN 'abandoned' THEN 5
                    ELSE 6
                END,
                t.priority DESC,
                t.id DESC
            """,
            (user_id,),
        ).fetchall()
        projects = db.execute(
            """
            SELECT id, name
            FROM projects
            WHERE user_id = ? AND status = 'active'
            ORDER BY priority DESC, id
            """,
            (user_id,),
        ).fetchall()
        goals = db.execute(
            """
            SELECT id, title
            FROM goals
            WHERE user_id = ? AND status = 'active'
            ORDER BY priority DESC, id
            """,
            (user_id,),
        ).fetchall()
        system_state = load_system_state(db, user_id)

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
    request: Request,
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

    user_id = request_user_id(request)
    clean_difficulty = normalize_difficulty(difficulty)
    xp_reward = xp_for_difficulty(clean_difficulty)
    parsed_project_id = optional_int(project_id)
    parsed_goal_id = (
        optional_int(goal_id)
        if not parsed_project_id
        else None
    )
    parsed_minutes = normalize_minutes(
        optional_int(estimated_minutes)
    )
    safe_priority = bounded_int(
        priority,
        default=5,
        low=1,
        high=10,
    )
    safe_energy = bounded_int(
        energy_required,
        default=3,
        low=1,
        high=5,
    )

    with get_db() as db:
        if parsed_project_id is not None:
            project = db.execute(
                """
                SELECT id
                FROM projects
                WHERE id = ? AND user_id = ?
                """,
                (parsed_project_id, user_id),
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
            INSERT INTO tasks (
                user_id,
                project_id,
                goal_id,
                title,
                description,
                status,
                priority,
                estimated_minutes,
                energy_required,
                due_date,
                difficulty,
                xp_reward,
                progress,
                quest_source,
                why
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                'backlog',
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                0,
                'manual',
                ?
            )
            """,
            (
                user_id,
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


@router.get(
    "/quests/{quest_id}",
    response_class=HTMLResponse,
)
def quest_detail(
    request: Request,
    quest_id: int,
):
    user_id = request_user_id(request)

    with get_db() as db:
        quest = db.execute(
            """
            SELECT
                t.*,
                p.name AS project_name,
                COALESCE(gt.title, gp.title) AS goal_title,
                l.id AS lead_id,
                l.company AS lead_company,
                l.pipeline_status AS lead_pipeline_status,
                l.next_action AS lead_next_action,
                l.next_action_due_date AS lead_next_action_due_date,
                l.deleted_at AS lead_deleted_at,
                COALESCE(
                    SUM(
                        COALESCE(
                            qu.session_minutes,
                            qu.actual_minutes,
                            0
                        )
                    ),
                    0
                ) AS total_session_minutes
            FROM tasks AS t
            LEFT JOIN projects AS p
              ON p.id = t.project_id
             AND p.user_id = t.user_id
            LEFT JOIN goals AS gt
              ON gt.id = t.goal_id
             AND gt.user_id = t.user_id
            LEFT JOIN goals AS gp
              ON gp.id = p.goal_id
             AND gp.user_id = t.user_id
            LEFT JOIN leads AS l
              ON l.quest_id = t.id
            LEFT JOIN quest_updates AS qu
              ON qu.task_id = t.id
             AND qu.user_id = t.user_id
            WHERE t.id = ? AND t.user_id = ?
            GROUP BY t.id
            """,
            (quest_id, user_id),
        ).fetchone()
        if not quest:
            raise HTTPException(
                status_code=404,
                detail="Quest not found",
            )

        updates = db.execute(
            """
            SELECT *
            FROM quest_updates
            WHERE task_id = ? AND user_id = ?
            ORDER BY id DESC
            """,
            (quest_id, user_id),
        ).fetchall()
        xp_award = db.execute(
            """
            SELECT *
            FROM xp_ledger
            WHERE task_id = ? AND user_id = ?
            """,
            (quest_id, user_id),
        ).fetchone()
        system_state = load_system_state(db, user_id)

    return templates.TemplateResponse(
        request=request,
        name="quest_detail.html",
        context={
            "quest": quest,
            "updates": updates,
            "xp_award": xp_award,
            "system_state": system_state,
            "completed_now": (
                request.query_params.get("completed") == "1"
            ),
            "duplicate_award": (
                request.query_params.get("duplicate") == "1"
            ),
            "result_required": (
                request.query_params.get("error")
                == "result_required"
            ),
            "levels_gained": (
                optional_int(
                    request.query_params.get("levels")
                )
                or 0
            ),
        },
    )


@router.post("/quests/{quest_id}/start")
def start_quest(
    request: Request,
    quest_id: int,
):
    user_id = request_user_id(request)
    with get_db() as db:
        destination = _client_hunting_destination(
            db,
            quest_id,
            user_id,
        )
        if destination:
            return RedirectResponse(
                url=destination,
                status_code=303,
            )
        try:
            set_quest_status(
                db,
                quest_id=quest_id,
                status="active",
                user_id=user_id,
            )
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail="Quest not found",
            )
    return RedirectResponse(
        url=f"/quests/{quest_id}",
        status_code=303,
    )


@router.post("/quests/{quest_id}/block")
def block_quest(
    request: Request,
    quest_id: int,
    blocker_reason: str = Form(default=""),
    note: str = Form(default=""),
):
    user_id = request_user_id(request)
    with get_db() as db:
        destination = _client_hunting_destination(
            db,
            quest_id,
            user_id,
        )
        if destination:
            return RedirectResponse(
                url=destination,
                status_code=303,
            )
        try:
            set_quest_status(
                db,
                quest_id=quest_id,
                status="blocked",
                note=note,
                blocker_reason=blocker_reason,
                user_id=user_id,
            )
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail="Quest not found",
            )
    return RedirectResponse(
        url=f"/quests/{quest_id}",
        status_code=303,
    )


@router.post("/quests/{quest_id}/unblock")
def unblock_quest(
    request: Request,
    quest_id: int,
):
    user_id = request_user_id(request)
    with get_db() as db:
        destination = _client_hunting_destination(
            db,
            quest_id,
            user_id,
        )
        if destination:
            return RedirectResponse(
                url=destination,
                status_code=303,
            )
        try:
            set_quest_status(
                db,
                quest_id=quest_id,
                status="active",
                note="Quest unblocked.",
                user_id=user_id,
            )
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail="Quest not found",
            )
    return RedirectResponse(
        url=f"/quests/{quest_id}",
        status_code=303,
    )


@router.post("/quests/{quest_id}/abandon")
def abandon_quest(
    request: Request,
    quest_id: int,
    note: str = Form(default=""),
):
    user_id = request_user_id(request)
    with get_db() as db:
        destination = _client_hunting_destination(
            db,
            quest_id,
            user_id,
        )
        if destination:
            return RedirectResponse(
                url=destination,
                status_code=303,
            )
        try:
            set_quest_status(
                db,
                quest_id=quest_id,
                status="abandoned",
                note=note,
                user_id=user_id,
            )
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail="Quest not found",
            )
    return RedirectResponse(
        url=f"/quests/{quest_id}",
        status_code=303,
    )


@router.post("/quests/{quest_id}/update")
def update_quest(
    request: Request,
    quest_id: int,
    note: str = Form(default=""),
    progress: int = Form(default=0),
    session_minutes: str = Form(default=""),
):
    user_id = request_user_id(request)
    parsed_minutes = normalize_minutes(
        optional_int(session_minutes)
    )

    with get_db() as db:
        destination = _client_hunting_destination(
            db,
            quest_id,
            user_id,
        )
        if destination:
            return RedirectResponse(
                url=destination,
                status_code=303,
            )
        try:
            update_quest_progress(
                db,
                quest_id=quest_id,
                note=note,
                progress=progress,
                session_minutes=parsed_minutes,
                user_id=user_id,
            )
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail="Quest not found",
            )

    return RedirectResponse(
        url=f"/quests/{quest_id}",
        status_code=303,
    )


@router.post("/quests/{quest_id}/complete")
def complete_quest(
    request: Request,
    quest_id: int,
    result_notes: str = Form(default=""),
    evidence: str = Form(default=""),
    session_minutes: str = Form(default=""),
):
    if not result_notes.strip():
        return RedirectResponse(
            url=(
                f"/quests/{quest_id}"
                "?error=result_required"
            ),
            status_code=303,
        )

    user_id = request_user_id(request)
    parsed_minutes = normalize_minutes(
        optional_int(session_minutes)
    )

    with get_db() as db:
        destination = _client_hunting_destination(
            db,
            quest_id,
            user_id,
        )
        if destination:
            return RedirectResponse(
                url=destination,
                status_code=303,
            )
        try:
            result = complete_quest_transaction(
                db,
                quest_id=quest_id,
                result_notes=result_notes,
                evidence=evidence,
                session_minutes=parsed_minutes,
                user_id=user_id,
            )
        except ValueError as exc:
            if str(exc) == "Quest not found":
                raise HTTPException(
                    status_code=404,
                    detail="Quest not found",
                )
            return RedirectResponse(
                url=(
                    f"/quests/{quest_id}"
                    "?error=result_required"
                ),
                status_code=303,
            )

    duplicate = "1" if result.duplicate_award else "0"
    return RedirectResponse(
        url=(
            f"/quests/{quest_id}"
            f"?completed=1"
            f"&levels={result.levels_gained}"
            f"&duplicate={duplicate}"
        ),
        status_code=303,
    )
