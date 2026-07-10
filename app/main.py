from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
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

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="MARK OS",
    version="0.2.0",
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


# IMPORTANT:
# SessionMiddleware is added after login_guard so it runs first on incoming requests.
# This ensures request.session exists before is_authenticated(request) is called.
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


def load_system_state(db) -> dict:
    game_state = db.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
    return {
        "level": game_state["level"] if game_state else 1,
        "xp_total": game_state["xp_total"] if game_state else None,
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
        system_state = load_system_state(db)

    return {
        "request": request,
        "profile": profile,
        "goals": goals,
        "projects": projects,
        "latest_checkin": latest_checkin,
        "direction": latest_direction,
        "checkin_count": checkin_count,
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

        direction = choose_direction(
            dict(checkin), dict(project) if project else None, previous_cash
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
            "name": "Projects & Tasks",
            "status": "next build",
            "description": "Turn goals into projects, projects into tasks, and tasks into today's quest.",
            "recommended": True,
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.2.0"}
