from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import get_db, init_db
from app.services.director import choose_direction

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="MARK OS", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.on_event("startup")
def startup() -> None:
    init_db()


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
        checkin_count = db.execute("SELECT COUNT(*) AS count FROM checkins").fetchone()["count"]

    return {
        "request": request,
        "profile": profile,
        "goals": goals,
        "projects": projects,
        "latest_checkin": latest_checkin,
        "direction": latest_direction,
        "checkin_count": checkin_count,
    }


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
            (cash, expenses, free_hours, energy, accomplished.strip(), blocker.strip(), notes.strip()),
        )
        checkin_id = cursor.lastrowid

        checkin = db.execute("SELECT * FROM checkins WHERE id = ?", (checkin_id,)).fetchone()
        project = db.execute(
            "SELECT * FROM projects WHERE status = 'active' ORDER BY priority DESC, id LIMIT 1"
        ).fetchone()

        direction = choose_direction(dict(checkin), dict(project) if project else None, previous_cash)
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

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={"rows": rows},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}
