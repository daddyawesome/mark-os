from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.database import get_db
from app.routes.shared import load_system_state, templates

router = APIRouter()


@router.get("/life-os", response_class=HTMLResponse)
def life_os(request: Request):
    with get_db() as db:
        counts = {
            "goals": db.execute("SELECT COUNT(*) AS count FROM goals").fetchone()[
                "count"
            ],
            "projects": db.execute(
                "SELECT COUNT(*) AS count FROM projects"
            ).fetchone()["count"],
            "tasks": db.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()[
                "count"
            ],
            "memories": db.execute(
                "SELECT COUNT(*) AS count FROM memories WHERE active = 1"
            ).fetchone()["count"],
            "timeline": db.execute(
                "SELECT COUNT(*) AS count FROM timeline_events"
            ).fetchone()["count"],
            "leads": db.execute(
                "SELECT COUNT(*) AS count FROM leads WHERE deleted_at IS NULL"
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
            "description": "Revised Phase 4: clickable quests with progress history, blockers, result-required completion, immutable XP, and level-up history.",
            "recommended": True,
        },
        {
            "icon": "✦",
            "name": "Client Hunting",
            "status": "live",
            "description": "A focused CRM for turning qualified opportunities into concrete follow-up quests.",
            "count": counts["leads"],
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
        context={"modules": modules, "counts": counts, "system_state": system_state},
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.3.0-client-hunting-mvp"}
