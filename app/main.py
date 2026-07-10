from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth import (
    IS_RAILWAY,
    SESSION_SECRET,
    credentials_configured,
    is_authenticated,
    safe_next_path,
    sign_in,
    sign_out,
    verify_credentials,
)
from app.database import get_db, init_db
from app.services.director import choose_direction
from app.services.gamification import (
    XP_BY_DIFFICULTY,
    apply_xp,
    normalize_difficulty,
    xp_for_difficulty,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="MARK OS",
    version="0.2.1",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

PUBLIC_PATHS = {"/login", "/health"}


@app.middleware("http")
async def login_guard(request: Request, call_next):
    path = request.url.path
    is_public = path in PUBLIC_PATHS or path.startswith("/static/")
    if not is_public and not is_authenticated(request):
        return RedirectResponse(url=f"/login?next={path}", status_code=303)
    return await call_next(request)


# SessionMiddleware is added after the login guard so it wraps the guard and
# request.session is always available before authentication is checked.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="mark_os_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=IS_RAILWAY,
)


@app.on_event("startup")
def startup() -> None:
    init_db()


def _optional_int(value: str | None) -> int | None:
    if value is None or not str(value).strip():
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _compute_effective_priority(quest: dict) -> float:
    """
    Blend task priority with the project's priority and, through the
    project or a direct link, the real goal's priority. A quest tied to
    a top-priority goal scores higher even if its own priority field
    was left at the default.
    """
    task_priority = quest.get("priority") or 5
    project_priority = quest.get("project_priority")
    goal_priority = quest.get("goal_priority")

    weighted = task_priority * 0.5
    weight_total = 0.5
    if project_priority is not None:
        weighted += project_priority * 0.3
        weight_total += 0.3
    if goal_priority is not None:
        weighted += goal_priority * 0.2
        weight_total += 0.2

    return round(weighted / weight_total, 2)


def _load_open_quests(db) -> list[dict]:
    """Open (non-completed) quests, each carrying its project/goal chain
    so the Director can score by effective priority, not just task.priority."""
    rows = db.execute(
        """
        SELECT
            t.*,
            p.name AS project_name,
            p.priority AS project_priority,
            p.goal_id AS project_goal_id,
            COALESCE(gt.priority, gp.priority) AS goal_priority,
            COALESCE(gt.title, gp.title) AS goal_title
        FROM tasks t
        LEFT JOIN projects p ON p.id = t.project_id
        LEFT JOIN goals gt ON gt.id = t.goal_id
        LEFT JOIN goals gp ON gp.id = p.goal_id
        WHERE t.status != 'completed'
        ORDER BY t.priority DESC, t.id
        """
    ).fetchall()

    quests = [dict(row) for row in rows]
    for quest in quests:
        quest["effective_priority"] = _compute_effective_priority(quest)
    return quests


def load_system_state(db) -> dict:
    game_state = db.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
    return {
        "level": game_state["level"] if game_state else 1,
        "xp_total": game_state["xp_total"] if game_state else None,
        "xp_into_level": game_state["xp_into_level"] if game_state else 0,
        "character_class": (
            game_state["character_class"]
            if game_state
            else "Data Builder / Future Business Owner"
        ),
        "threshold_mode": game_state["threshold_mode"] if game_state else "hidden",
        "memory_count": db.execute(
            "SELECT COUNT(*) AS count FROM memories WHERE active = 1"
        ).fetchone()["count"],
        "timeline_count": db.execute(
            "SELECT COUNT(*) AS count FROM timeline_events"
        ).fetchone()["count"],
        "task_count": db.execute(
            "SELECT COUNT(*) AS count FROM tasks WHERE status != 'completed'"
        ).fetchone()["count"],
    }


def dashboard_context(request: Request) -> dict:
    with get_db() as db:
        profile = db.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        goals = db.execute(
            "SELECT * FROM goals WHERE status = 'active' ORDER BY priority DESC, id"
        ).fetchall()
        projects = db.execute(
            "SELECT * FROM projects WHERE status = 'active' ORDER BY priority DESC, id"
        ).fetchall()
        latest_checkin = db.execute(
            "SELECT * FROM checkins ORDER BY id DESC LIMIT 1"
        ).fetchone()
        latest_direction = db.execute(
            """
            SELECT d.*
            FROM directions d
            JOIN checkins c ON c.id = d.checkin_id
            ORDER BY d.id DESC
            LIMIT 1
            """
        ).fetchone()
        checkin_count = db.execute(
            "SELECT COUNT(*) AS count FROM checkins"
        ).fetchone()["count"]
        active_quests = db.execute(
            """
            SELECT t.*, p.name AS project_name
            FROM tasks t
            LEFT JOIN projects p ON p.id = t.project_id
            WHERE t.status != 'completed'
            ORDER BY CASE t.status WHEN 'active' THEN 0 ELSE 1 END,
                     t.priority DESC, t.id
            LIMIT 3
            """
        ).fetchall()
        system_state = load_system_state(db)

    return {
        "request": request,
        "profile": profile,
        "goals": goals,
        "projects": projects,
        "latest_checkin": latest_checkin,
        "direction": latest_direction,
        "checkin_count": checkin_count,
        "active_quests": active_quests,
        "system_state": system_state,
    }


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "next": safe_next_path(next),
            "error": None,
            "configured": credentials_configured(),
        },
    )


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
):
    destination = safe_next_path(next)
    if verify_credentials(username.strip(), password):
        sign_in(request)
        return RedirectResponse(url=destination, status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "next": destination,
            "error": (
                "Login is not configured yet. Set MARK_OS_PASSWORD in Railway."
                if not credentials_configured()
                else "The username or password is incorrect."
            ),
            "configured": credentials_configured(),
        },
        status_code=401,
    )


@app.post("/logout")
def logout(request: Request):
    sign_out(request)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=dashboard_context(request),
    )


@app.post("/check-in", response_class=HTMLResponse)
def create_checkin(
    request: Request,
    cash: float | None = Form(default=None),
    expenses: float = Form(default=0),
    free_hours: float = Form(default=0),
    energy: int = Form(default=3),
    accomplished: str = Form(default=""),
    blocker: str = Form(default=""),
    notes: str = Form(default=""),
):
    energy = max(1, min(5, energy))
    free_hours = max(0, free_hours)
    expenses = max(0, expenses)

    with get_db() as db:
        previous = db.execute(
            "SELECT cash FROM checkins WHERE cash IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_cash = previous["cash"] if previous else None

        cursor = db.execute(
            """
            INSERT INTO checkins
            (cash, expenses, free_hours, energy, accomplished, blocker, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cash,
                expenses,
                free_hours,
                energy,
                accomplished.strip(),
                blocker.strip(),
                notes.strip(),
            ),
        )
        checkin_id = cursor.lastrowid
        checkin = db.execute(
            "SELECT * FROM checkins WHERE id = ?", (checkin_id,)
        ).fetchone()
        project = db.execute(
            """
            SELECT * FROM projects
            WHERE status = 'active'
            ORDER BY priority DESC, id
            LIMIT 1
            """
        ).fetchone()

        open_quests = _load_open_quests(db)

        direction = choose_direction(
            dict(checkin),
            dict(project) if project else None,
            previous_cash,
            open_quests,
        )
        db.execute(
            """
            INSERT INTO directions
            (checkin_id, main_quest, why, side_quest_1, side_quest_2, avoid, signal)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkin_id,
                direction.main_quest,
                direction.why,
                direction.side_quest_1,
                direction.side_quest_2,
                direction.avoid,
                direction.signal,
            ),
        )
        saved_direction = db.execute(
            "SELECT * FROM directions WHERE checkin_id = ?", (checkin_id,)
        ).fetchone()

    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="partials/direction.html",
            context={
                "direction": saved_direction,
                "latest_checkin": checkin,
            },
        )
    return RedirectResponse(url="/", status_code=303)


@app.get("/quests", response_class=HTMLResponse)
def quests(request: Request):
    with get_db() as db:
        rows = db.execute(
            """
            SELECT
                t.*,
                p.name AS project_name,
                COALESCE(gt.title, gp.title) AS goal_title
            FROM tasks t
            LEFT JOIN projects p ON p.id = t.project_id
            LEFT JOIN goals gt ON gt.id = t.goal_id
            LEFT JOIN goals gp ON gp.id = p.goal_id
            ORDER BY CASE t.status
                        WHEN 'active' THEN 0
                        WHEN 'backlog' THEN 1
                        WHEN 'completed' THEN 2
                        ELSE 3
                     END,
                     t.priority DESC,
                     t.id DESC
            """
        ).fetchall()
        projects = db.execute(
            "SELECT id, name FROM projects WHERE status = 'active' ORDER BY priority DESC, id"
        ).fetchall()
        goals = db.execute(
            "SELECT id, title FROM goals WHERE status = 'active' ORDER BY priority DESC, id"
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


@app.post("/quests")
def create_quest(
    title: str = Form(...),
    description: str = Form(default=""),
    project_id: str = Form(default=""),
    goal_id: str = Form(default=""),
    difficulty: str = Form(default="normal"),
    estimated_minutes: str = Form(default=""),
    due_date: str = Form(default=""),
):
    clean_title = title.strip()
    if not clean_title:
        return RedirectResponse(url="/quests", status_code=303)

    clean_difficulty = normalize_difficulty(difficulty)
    xp_reward = xp_for_difficulty(clean_difficulty)
    parsed_project_id = _optional_int(project_id)
    parsed_goal_id = _optional_int(goal_id) if not parsed_project_id else None
    parsed_minutes = _optional_int(estimated_minutes)

    with get_db() as db:
        db.execute(
            """
            INSERT INTO tasks
            (project_id, goal_id, title, description, status, priority, estimated_minutes,
             due_date, difficulty, xp_reward, progress)
            VALUES (?, ?, ?, ?, 'backlog', 5, ?, ?, ?, ?, 0)
            """,
            (
                parsed_project_id,
                parsed_goal_id,
                clean_title,
                description.strip(),
                parsed_minutes,
                due_date.strip() or None,
                clean_difficulty,
                xp_reward,
            ),
        )

    return RedirectResponse(url="/quests", status_code=303)


@app.get("/quests/{quest_id}", response_class=HTMLResponse)
def quest_detail(request: Request, quest_id: int):
    with get_db() as db:
        quest = db.execute(
            """
            SELECT
                t.*,
                p.name AS project_name,
                COALESCE(gt.title, gp.title) AS goal_title
            FROM tasks t
            LEFT JOIN projects p ON p.id = t.project_id
            LEFT JOIN goals gt ON gt.id = t.goal_id
            LEFT JOIN goals gp ON gp.id = p.goal_id
            WHERE t.id = ?
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
            "levels_gained": _optional_int(request.query_params.get("levels")) or 0,
        },
    )


@app.post("/quests/{quest_id}/start")
def start_quest(quest_id: int):
    with get_db() as db:
        quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
        if not quest:
            raise HTTPException(status_code=404, detail="Quest not found")

        if quest["status"] != "completed":
            db.execute(
                """
                UPDATE tasks
                SET status = 'active',
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
                WHERE id = ?
                """,
                (quest_id,),
            )
            db.execute(
                """
                INSERT INTO quest_updates (task_id, note, progress, event_type)
                VALUES (?, 'Quest started.', ?, 'started')
                """,
                (quest_id, quest["progress"]),
            )

    return RedirectResponse(url=f"/quests/{quest_id}", status_code=303)


@app.post("/quests/{quest_id}/update")
def update_quest(
    quest_id: int,
    note: str = Form(default=""),
    progress: int = Form(default=0),
    actual_minutes: str = Form(default=""),
):
    safe_progress = max(0, min(99, progress))
    parsed_minutes = _optional_int(actual_minutes)

    with get_db() as db:
        quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
        if not quest:
            raise HTTPException(status_code=404, detail="Quest not found")
        if quest["status"] == "completed":
            return RedirectResponse(url=f"/quests/{quest_id}", status_code=303)

        db.execute(
            """
            UPDATE tasks
            SET status = 'active',
                progress = ?,
                actual_minutes = COALESCE(?, actual_minutes),
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
            WHERE id = ?
            """,
            (safe_progress, parsed_minutes, quest_id),
        )
        db.execute(
            """
            INSERT INTO quest_updates
            (task_id, note, progress, actual_minutes, event_type)
            VALUES (?, ?, ?, ?, 'update')
            """,
            (quest_id, note.strip(), safe_progress, parsed_minutes),
        )

    return RedirectResponse(url=f"/quests/{quest_id}", status_code=303)


@app.post("/quests/{quest_id}/complete")
def complete_quest(
    quest_id: int,
    result_notes: str = Form(default=""),
    actual_minutes: str = Form(default=""),
):
    parsed_minutes = _optional_int(actual_minutes)
    levels_gained = 0

    with get_db() as db:
        quest = db.execute("SELECT * FROM tasks WHERE id = ?", (quest_id,)).fetchone()
        if not quest:
            raise HTTPException(status_code=404, detail="Quest not found")

        if quest["status"] == "completed":
            return RedirectResponse(url=f"/quests/{quest_id}", status_code=303)

        state = db.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
        level_before = state["level"] if state else 1
        xp_total_before = state["xp_total"] if state else None
        xp_into_level_before = state["xp_into_level"] if state else 0
        xp_reward = max(0, int(quest["xp_reward"] or 0))

        db.execute(
            """
            UPDATE tasks
            SET status = 'completed',
                progress = 100,
                completed_at = CURRENT_TIMESTAMP,
                result_notes = ?,
                actual_minutes = COALESCE(?, actual_minutes)
            WHERE id = ?
            """,
            (result_notes.strip(), parsed_minutes, quest_id),
        )

        ledger_insert = db.execute(
            """
            INSERT OR IGNORE INTO xp_ledger
            (task_id, xp_delta, level_before, level_after, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                quest_id,
                xp_reward,
                level_before,
                level_before,
                f"Completed quest: {quest['title']}",
            ),
        )

        if ledger_insert.rowcount:
            award = apply_xp(
                level=level_before,
                xp_total=xp_total_before,
                xp_into_level=xp_into_level_before,
                awarded_xp=xp_reward,
            )
            levels_gained = award.levels_gained

            db.execute(
                """
                UPDATE game_state
                SET level = ?,
                    xp_total = ?,
                    xp_into_level = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    last_level_up_at = CASE WHEN ? > 0 THEN CURRENT_TIMESTAMP ELSE last_level_up_at END,
                    source = 'quest_engine'
                WHERE id = 1
                """,
                (
                    award.level,
                    award.xp_total,
                    award.xp_into_level,
                    award.levels_gained,
                ),
            )
            db.execute(
                "UPDATE xp_ledger SET level_after = ? WHERE task_id = ?",
                (award.level, quest_id),
            )

            db.execute(
                """
                INSERT INTO quest_updates
                (task_id, note, progress, actual_minutes, event_type)
                VALUES (?, ?, 100, ?, 'completed')
                """,
                (
                    quest_id,
                    result_notes.strip() or "Quest completed.",
                    parsed_minutes,
                ),
            )

            db.execute(
                """
                INSERT INTO timeline_events
                (event_date, event_type, title, summary, details_json,
                 status, importance, source)
                VALUES (date('now', 'localtime'), 'quest_completed', ?, ?, ?,
                        'completed', 8, 'quest_engine')
                """,
                (
                    quest["title"],
                    result_notes.strip() or f"Completed quest and earned {xp_reward} XP.",
                    json.dumps(
                        {
                            "task_id": quest_id,
                            "xp_awarded": xp_reward,
                            "level_before": level_before,
                            "level_after": award.level,
                        }
                    ),
                ),
            )

            if award.levels_gained > 0:
                db.execute(
                    """
                    INSERT INTO game_history
                    (event_date, level, xp_total, event, source)
                    VALUES (date('now', 'localtime'), ?, ?, ?, 'quest_engine')
                    """,
                    (
                        award.level,
                        award.xp_total,
                        f"Level up after completing: {quest['title']}",
                    ),
                )
                db.execute(
                    """
                    INSERT INTO timeline_events
                    (event_date, event_type, title, summary, details_json,
                     status, importance, source)
                    VALUES (date('now', 'localtime'), 'level_up', ?, ?, ?,
                            'completed', 10, 'quest_engine')
                    """,
                    (
                        f"Reached Level {award.level}",
                        "Quest progress crossed a hidden level threshold.",
                        json.dumps(
                            {
                                "level_before": level_before,
                                "level_after": award.level,
                                "levels_gained": award.levels_gained,
                            }
                        ),
                    ),
                )

    return RedirectResponse(
        url=f"/quests/{quest_id}?completed=1&levels={levels_gained}",
        status_code=303,
    )


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    with get_db() as db:
        rows = db.execute(
            """
            SELECT c.*, d.main_quest, d.signal
            FROM checkins c
            LEFT JOIN directions d ON d.checkin_id = c.id
            ORDER BY c.id DESC
            LIMIT 30
            """
        ).fetchall()
        system_state = load_system_state(db)

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={"rows": rows, "system_state": system_state},
    )


@app.get("/life-os", response_class=HTMLResponse)
def life_os(request: Request):
    with get_db() as db:
        counts = {
            "goals": db.execute("SELECT COUNT(*) AS count FROM goals").fetchone()["count"],
            "projects": db.execute("SELECT COUNT(*) AS count FROM projects").fetchone()["count"],
            "tasks": db.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()["count"],
            "memories": db.execute(
                "SELECT COUNT(*) AS count FROM memories WHERE active = 1"
            ).fetchone()["count"],
            "timeline": db.execute(
                "SELECT COUNT(*) AS count FROM timeline_events"
            ).fetchone()["count"],
        }
        system_state = load_system_state(db)

    modules = [
        {
            "icon": "⌂",
            "name": "Today",
            "status": "live",
            "description": "Current state, daily check-in, and one highest-leverage direction.",
        },
        {
            "icon": "◎",
            "name": "Goals & Vision",
            "status": "foundation",
            "description": "Long-term outcomes and the reasons behind them.",
        },
        {
            "icon": "▣",
            "name": "Projects & Quests",
            "status": "live",
            "description": "Clickable quests with progress notes, completion evidence, XP, and automatic leveling.",
            "recommended": True,
        },
        {
            "icon": "✦",
            "name": "AI Chat",
            "status": "next build",
            "description": "Budget-safe assistant chat using recent messages plus selected long-term memory.",
        },
        {
            "icon": "✎",
            "name": "Notes & Knowledge",
            "status": "planned",
            "description": "A second brain for ideas, technical solutions, lessons, and references.",
        },
        {
            "icon": "◉",
            "name": "Routines & Focus",
            "status": "planned",
            "description": "Morning, work-session, and evening operating routines.",
        },
        {
            "icon": "🔥",
            "name": "Habits",
            "status": "planned",
            "description": "Track systems that support goals instead of chasing motivation.",
        },
        {
            "icon": "☰",
            "name": "Journal & Reflection",
            "status": "planned",
            "description": "Daily and weekly evidence about what worked, failed, and changed.",
        },
        {
            "icon": "₱",
            "name": "Finance",
            "status": "planned",
            "description": "Cash, income, expenses, reserves, bills, and business revenue.",
        },
        {
            "icon": "□",
            "name": "Calendar",
            "status": "planned",
            "description": "Real time constraints so recommendations fit the day that actually exists.",
        },
    ]

    return templates.TemplateResponse(
        request=request,
        name="life_os.html",
        context={
            "modules": modules,
            "counts": counts,
            "system_state": system_state,
        },
    )


@app.get("/goals", response_class=HTMLResponse)
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
            "SELECT id, name FROM projects WHERE goal_id IS NULL ORDER BY priority DESC, id"
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


@app.post("/goals")
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


@app.post("/projects/{project_id}/link-goal")
def link_project_goal(project_id: int, goal_id: str = Form(default="")):
    parsed_goal_id = _optional_int(goal_id)

    with get_db() as db:
        project = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        db.execute(
            "UPDATE projects SET goal_id = ? WHERE id = ?",
            (parsed_goal_id, project_id),
        )

    return RedirectResponse(url="/goals", status_code=303)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.2.1"}