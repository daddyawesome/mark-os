from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import load_open_quests, load_system_state, templates
from app.services.director import choose_direction
from app.services.personal_scope import request_user_id


router = APIRouter()


def dashboard_context(request: Request) -> dict:
    user_id = request_user_id(request)

    with get_db() as db:
        profile = db.execute(
            "SELECT * FROM profile WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        goals = db.execute(
            """
            SELECT *
            FROM goals
            WHERE user_id = ? AND status = 'active'
            ORDER BY priority DESC, id
            """,
            (user_id,),
        ).fetchall()
        projects = db.execute(
            """
            SELECT *
            FROM projects
            WHERE user_id = ? AND status = 'active'
            ORDER BY priority DESC, id
            """,
            (user_id,),
        ).fetchall()
        latest_checkin = db.execute(
            """
            SELECT *
            FROM checkins
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        latest_direction = db.execute(
            """
            SELECT d.*
            FROM directions AS d
            JOIN checkins AS c
              ON c.id = d.checkin_id
             AND c.user_id = d.user_id
            WHERE d.user_id = ?
            ORDER BY d.id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        checkin_count = db.execute(
            """
            SELECT COUNT(*) AS count
            FROM checkins
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()["count"]
        active_quests = db.execute(
            """
            SELECT t.*, p.name AS project_name
            FROM tasks AS t
            LEFT JOIN projects AS p
              ON p.id = t.project_id
             AND p.user_id = t.user_id
            WHERE t.user_id = ?
              AND t.status NOT IN ('completed', 'abandoned', 'closed')
            ORDER BY
                CASE t.status
                    WHEN 'active' THEN 0
                    WHEN 'blocked' THEN 1
                    ELSE 2
                END,
                t.priority DESC,
                t.id
            LIMIT 3
            """,
            (user_id,),
        ).fetchall()
        system_state = load_system_state(db, user_id)

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
    user_id = request_user_id(request)
    energy = max(1, min(5, energy))
    free_hours = max(0, free_hours)
    cash_in = max(0, cash_in)
    expenses = max(0, expenses)

    with get_db() as db:
        previous = db.execute(
            """
            SELECT cash
            FROM checkins
            WHERE user_id = ? AND cash IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        previous_cash = float(previous["cash"]) if previous else 0
        new_cash_balance = previous_cash + cash_in - expenses

        cursor = db.execute(
            """
            INSERT INTO checkins (
                user_id,
                cash,
                cash_in,
                expenses,
                free_hours,
                energy,
                accomplished,
                blocker,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
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
        checkin_id = int(cursor.lastrowid)

        checkin = db.execute(
            """
            SELECT *
            FROM checkins
            WHERE id = ? AND user_id = ?
            """,
            (checkin_id, user_id),
        ).fetchone()

        project = db.execute(
            """
            SELECT *
            FROM projects
            WHERE user_id = ? AND status = 'active'
            ORDER BY priority DESC, id
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        open_quests = load_open_quests(db, user_id)
        direction = choose_direction(
            dict(checkin),
            dict(project) if project else None,
            previous_cash,
            open_quests,
        )

        db.execute(
            """
            INSERT INTO directions (
                user_id,
                checkin_id,
                main_quest,
                why,
                side_quest_1,
                side_quest_2,
                avoid,
                signal
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
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
            """
            SELECT *
            FROM directions
            WHERE checkin_id = ? AND user_id = ?
            """,
            (checkin_id, user_id),
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


def _parse_optional_float(
    value: str | float | None,
) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _movement_delta(
    cash_in: float | None,
    expenses: float,
) -> float | None:
    if cash_in is None:
        return None
    return float(cash_in) - float(expenses or 0)


def _adjust_later_cash_balances(
    db,
    *,
    user_id: int,
    after_checkin_id: int,
    delta: float,
) -> None:
    if abs(delta) < 0.00001:
        return

    db.execute(
        """
        UPDATE checkins
        SET cash = cash + ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
          AND id > ?
          AND cash IS NOT NULL
          AND cash_in IS NOT NULL
        """,
        (delta, user_id, after_checkin_id),
    )


def _previous_cash_before(
    db,
    *,
    user_id: int,
    checkin_id: int,
) -> float:
    previous = db.execute(
        """
        SELECT cash
        FROM checkins
        WHERE user_id = ?
          AND id < ?
          AND cash IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, checkin_id),
    ).fetchone()
    return float(previous["cash"]) if previous else 0


@router.get(
    "/history/{checkin_id}/edit",
    response_class=HTMLResponse,
)
def edit_checkin_page(
    request: Request,
    checkin_id: int,
):
    user_id = request_user_id(request)

    with get_db() as db:
        checkin = db.execute(
            """
            SELECT *
            FROM checkins
            WHERE id = ? AND user_id = ?
            """,
            (checkin_id, user_id),
        ).fetchone()
        if not checkin:
            raise HTTPException(
                status_code=404,
                detail="Check-in not found",
            )
        system_state = load_system_state(db, user_id)

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
    request: Request,
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
    user_id = request_user_id(request)
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
            WHERE id = ? AND user_id = ?
            """,
            (checkin_id, user_id),
        ).fetchone()
        if not old:
            raise HTTPException(
                status_code=404,
                detail="Check-in not found",
            )

        old_cash_in = (
            old["cash_in"]
            if "cash_in" in old.keys()
            else None
        )
        old_expenses = float(old["expenses"] or 0)
        old_movement = _movement_delta(
            old_cash_in,
            old_expenses,
        )

        if parsed_cash_balance is not None:
            new_cash_balance = parsed_cash_balance
        elif parsed_cash_in is not None:
            previous_cash = _previous_cash_before(
                db,
                user_id=user_id,
                checkin_id=checkin_id,
            )
            new_cash_balance = (
                previous_cash + parsed_cash_in - expenses
            )
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
            WHERE id = ? AND user_id = ?
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
                user_id,
            ),
        )
        new_movement = _movement_delta(
            parsed_cash_in,
            expenses,
        )

        if (
            old_movement is not None
            and new_movement is not None
        ):
            _adjust_later_cash_balances(
                db,
                user_id=user_id,
                after_checkin_id=checkin_id,
                delta=new_movement - old_movement,
            )

        checkin = db.execute(
            """
            SELECT *
            FROM checkins
            WHERE id = ? AND user_id = ?
            """,
            (checkin_id, user_id),
        ).fetchone()
        previous_cash = _previous_cash_before(
            db,
            user_id=user_id,
            checkin_id=checkin_id,
        )
        project = db.execute(
            """
            SELECT *
            FROM projects
            WHERE user_id = ? AND status = 'active'
            ORDER BY priority DESC, id
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        open_quests = load_open_quests(db, user_id)
        direction = choose_direction(
            dict(checkin),
            dict(project) if project else None,
            previous_cash,
            open_quests,
        )

        db.execute(
            """
            DELETE FROM directions
            WHERE checkin_id = ? AND user_id = ?
            """,
            (checkin_id, user_id),
        )
        db.execute(
            """
            INSERT INTO directions (
                user_id,
                checkin_id,
                main_quest,
                why,
                side_quest_1,
                side_quest_2,
                avoid,
                signal
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
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
def delete_checkin(
    request: Request,
    checkin_id: int,
):
    user_id = request_user_id(request)

    with get_db() as db:
        old = db.execute(
            """
            SELECT *
            FROM checkins
            WHERE id = ? AND user_id = ?
            """,
            (checkin_id, user_id),
        ).fetchone()
        if not old:
            raise HTTPException(
                status_code=404,
                detail="Check-in not found",
            )

        old_cash_in = (
            old["cash_in"]
            if "cash_in" in old.keys()
            else None
        )
        old_expenses = float(old["expenses"] or 0)
        old_movement = _movement_delta(
            old_cash_in,
            old_expenses,
        )

        db.execute(
            """
            DELETE FROM directions
            WHERE checkin_id = ? AND user_id = ?
            """,
            (checkin_id, user_id),
        )
        db.execute(
            """
            DELETE FROM checkins
            WHERE id = ? AND user_id = ?
            """,
            (checkin_id, user_id),
        )

        if old_movement is not None:
            _adjust_later_cash_balances(
                db,
                user_id=user_id,
                after_checkin_id=checkin_id,
                delta=-old_movement,
            )

    return RedirectResponse(url="/history", status_code=303)


@router.get("/history", response_class=HTMLResponse)
def history(request: Request):
    user_id = request_user_id(request)

    with get_db() as db:
        rows = db.execute(
            """
            SELECT c.*, d.main_quest, d.signal
            FROM checkins AS c
            LEFT JOIN directions AS d
              ON d.checkin_id = c.id
             AND d.user_id = c.user_id
            WHERE c.user_id = ?
            ORDER BY c.id DESC
            LIMIT 30
            """,
            (user_id,),
        ).fetchall()
        timeline_rows = db.execute(
            """
            SELECT *
            FROM timeline_events
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 30
            """,
            (user_id,),
        ).fetchall()
        system_state = load_system_state(db, user_id)

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "rows": rows,
            "timeline_rows": timeline_rows,
            "system_state": system_state,
        },
    )
