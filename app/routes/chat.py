from __future__ import annotations

from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import load_system_state, templates
from app.services.chat import (
    MAX_RECENT_MESSAGES,
    create_chat_session,
    get_chat_session,
    get_recent_chat_messages,
    list_chat_sessions,
)
from app.services.chat_orchestrator import send_chat_message
from app.services.personal_scope import request_user_id


router = APIRouter(prefix="/chat")


def _require_session(db, session_id: int, user_id: int):
    session = get_chat_session(db, session_id, user_id=user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


def _thread_context(request: Request, session_id: int, *, error: str | None = None) -> dict:
    user_id = request_user_id(request)
    with get_db() as db:
        session = _require_session(db, session_id, user_id)
        messages = get_recent_chat_messages(
            db, session_id, limit=MAX_RECENT_MESSAGES, user_id=user_id
        )
        sessions = list_chat_sessions(db, user_id=user_id)
        system_state = load_system_state(db, user_id)
    return {
        "request": request,
        "session": session,
        "messages": messages,
        "sessions": sessions,
        "system_state": system_state,
        "error": error,
        "request_key": uuid4().hex,
    }


@router.get("", response_class=HTMLResponse)
def chat_home(request: Request):
    user_id = request_user_id(request)
    with get_db() as db:
        sessions = list_chat_sessions(db, user_id=user_id)
        if sessions:
            return RedirectResponse(url=f"/chat/{sessions[0]['id']}", status_code=303)
        system_state = load_system_state(db, user_id)
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context={
            "session": None,
            "messages": [],
            "sessions": [],
            "system_state": system_state,
            "error": None,
        },
    )


@router.post("/new")
def start_chat_session(request: Request):
    user_id = request_user_id(request)
    with get_db() as db:
        session = create_chat_session(db, user_id=user_id)
    return RedirectResponse(url=f"/chat/{session['id']}", status_code=303)


@router.get("/{session_id}", response_class=HTMLResponse)
def chat_thread(request: Request, session_id: int):
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context=_thread_context(
            request, session_id, error=request.query_params.get("error")
        ),
    )


@router.post("/{session_id}/messages")
def post_chat_message(
    request: Request,
    session_id: int,
    content: str = Form(default=""),
    request_key: str = Form(default=""),
):
    user_id = request_user_id(request)
    is_htmx = request.headers.get("hx-request", "").lower() == "true"

    with get_db() as db:
        _require_session(db, session_id, user_id)
        try:
            send_chat_message(
                db,
                session_id=session_id,
                content=content,
                request_key=request_key or None,
                user_id=user_id,
            )
        except ValueError as exc:
            if is_htmx:
                context = _thread_context(request, session_id, error=str(exc))
                return templates.TemplateResponse(
                    request=request,
                    name="partials/chat_messages.html",
                    context=context,
                    status_code=422,
                )
            return RedirectResponse(
                url=f"/chat/{session_id}?error={quote(str(exc))}",
                status_code=303,
            )

    if is_htmx:
        return templates.TemplateResponse(
            request=request,
            name="partials/chat_messages.html",
            context=_thread_context(request, session_id),
        )
    return RedirectResponse(url=f"/chat/{session_id}", status_code=303)
