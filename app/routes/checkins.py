from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import load_open_quests, load_system_state, templates
from app.services.director import choose_direction

router = APIRouter()


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
            WHERE t.status NOT IN ('completed', 'abandoned', 'closed')
            ORDER BY CASE t.status WHEN 'active' THEN 0 WHEN 'blocked' THEN 1 ELSE 2 END,
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


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=dashboard_context(request),
    )


@router.post("/check-in", response_class=HTMLResponse)
def create_checkin(
    request: Request,
    cash_in: float = Form(default=0),
    expenses: float = Form(default=0),
    free_hours: float = Form(default=0),
    energy: int = Form(default=3),
    accomplished: str = Form(default=""),
    blocker: str = Form(default=""),
    notes: str = Form(default=""),
):
    energy = max(1, min(5, energy))
    free_hours = max(0, free_hours)
    cash_in = max(0, cash_in)
    expenses = max(0, expenses)

    with get_db() as db:
        previous = db.execute(
            """
            SELECT cash
            FROM checkins
            WHERE cash IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

        previous_cash = float(previous["cash"]) if previous else 0
        new_cash_balance = previous_cash + cash_in - expenses

        cursor = db.execute(
            """
            INSERT INTO checkins
                (cash, cash_in, expenses, free_hours, energy, accomplished, blocker, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_cash_balance,
                cash_in,
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
            "SELECT * FROM checkins WHERE id = ?",
            (checkin_id,),
        ).fetchone()

        project = db.execute(
            """
            SELECT *
            FROM projects
            WHERE status = 'active'
            ORDER BY priority DESC, id
            LIMIT 1
            """
        ).fetchone()

        open_quests = load_open_quests(db)

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
            "SELECT * FROM directions WHERE checkin_id = ?",
            (checkin_id,),
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


def _parse_optional_float(value: str | float | None) -> float | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def _movement_delta(cash_in: float | None, expenses: float) -> float | None:
    if cash_in is None:
        return None
    return float(cash_in) - float(expenses or 0)


def _adjust_later_cash_balances(db, *, after_checkin_id: int, delta: float) -> None:
    """
    Adjust only later movement-based check-ins.

    Imported historical balance rows usually have cash_in = NULL,
    so they are treated as absolute historical balances and not recalculated.
    """
    if abs(delta) < 0.00001:
        return

    db.execute(
        """
        UPDATE checkins
        SET cash = cash + ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id > ?
          AND cash IS NOT NULL
          AND cash_in IS NOT NULL
        """,
        (delta, after_checkin_id),
    )


def _previous_cash_before(db, checkin_id: int) -> float:
    previous = db.execute(
        """
        SELECT cash
        FROM checkins
        WHERE id < ?
          AND cash IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (checkin_id,),
    ).fetchone()
    return float(previous["cash"]) if previous else 0


@router.get("/history/{checkin_id}/edit", response_class=HTMLResponse)
def edit_checkin_page(request: Request, checkin_id: int):
    with get_db() as db:
        checkin = db.execute(
            """
            SELECT *
            FROM checkins
            WHERE id = ?
            """,
            (checkin_id,),
        ).fetchone()

        if not checkin:
            raise HTTPException(status_code=404, detail="Check-in not found")

        system_state = load_system_state(db)

    return templates.TemplateResponse(
        request=request,
        name="edit_checkin.html",
        context={
            "checkin": checkin,
            "system_state": system_state,
        },
    )


@router.post("/history/{checkin_id}/edit")
def edit_checkin_submit(
    checkin_id: int,
    cash_in: str = Form(default=""),
    cash_balance: str = Form(default=""),
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

    parsed_cash_in = _parse_optional_float(cash_in)
    parsed_cash_balance = _parse_optional_float(cash_balance)

    if parsed_cash_in is not None:
        parsed_cash_in = max(0, parsed_cash_in)

    with get_db() as db:
        old = db.execute(
            """
            SELECT *
            FROM checkins
            WHERE id = ?
            """,
            (checkin_id,),
        ).fetchone()

        if not old:
            raise HTTPException(status_code=404, detail="Check-in not found")

        old_cash_in = old["cash_in"] if "cash_in" in old.keys() else None
        old_expenses = float(old["expenses"] or 0)
        old_movement = _movement_delta(old_cash_in, old_expenses)

        if parsed_cash_balance is not None:
            new_cash_balance = parsed_cash_balance
        elif parsed_cash_in is not None:
            previous_cash = _previous_cash_before(db, checkin_id)
            new_cash_balance = previous_cash + parsed_cash_in - expenses
        else:
            new_cash_balance = old["cash"]

        db.execute(
            """
            UPDATE checkins
            SET cash = ?,
                cash_in = ?,
                expenses = ?,
                free_hours = ?,
                energy = ?,
                accomplished = ?,
                blocker = ?,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                new_cash_balance,
                parsed_cash_in,
                expenses,
                free_hours,
                energy,
                accomplished.strip(),
                blocker.strip(),
                notes.strip(),
                checkin_id,
            ),
        )

        new_movement = _movement_delta(parsed_cash_in, expenses)

        if old_movement is not None and new_movement is not None:
            _adjust_later_cash_balances(
                db,
                after_checkin_id=checkin_id,
                delta=new_movement - old_movement,
            )

        checkin = db.execute(
            "SELECT * FROM checkins WHERE id = ?",
            (checkin_id,),
        ).fetchone()
        previous_cash = _previous_cash_before(db, checkin_id)

        project = db.execute(
            """
            SELECT *
            FROM projects
            WHERE status = 'active'
            ORDER BY priority DESC, id
            LIMIT 1
            """
        ).fetchone()

        open_quests = load_open_quests(db)
        direction = choose_direction(
            dict(checkin),
            dict(project) if project else None,
            previous_cash,
            open_quests,
        )

        db.execute("DELETE FROM directions WHERE checkin_id = ?", (checkin_id,))
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

    return RedirectResponse(url="/history", status_code=303)


@router.post("/history/{checkin_id}/delete")
def delete_checkin(checkin_id: int):
    with get_db() as db:
        old = db.execute(
            "SELECT * FROM checkins WHERE id = ?",
            (checkin_id,),
        ).fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="Check-in not found")

        old_cash_in = old["cash_in"] if "cash_in" in old.keys() else None
        old_expenses = float(old["expenses"] or 0)
        old_movement = _movement_delta(old_cash_in, old_expenses)

        db.execute("DELETE FROM directions WHERE checkin_id = ?", (checkin_id,))
        db.execute("DELETE FROM checkins WHERE id = ?", (checkin_id,))

        if old_movement is not None:
            _adjust_later_cash_balances(
                db,
                after_checkin_id=checkin_id,
                delta=-old_movement,
            )

    return RedirectResponse(url="/history", status_code=303)


@router.get("/history", response_class=HTMLResponse)
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
        timeline_rows = db.execute(
            """
            SELECT * FROM timeline_events
            ORDER BY id DESC
            LIMIT 30
            """
        ).fetchall()
        system_state = load_system_state(db)

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "rows": rows,
            "timeline_rows": timeline_rows,
            "system_state": system_state,
        },
    )
