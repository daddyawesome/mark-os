from __future__ import annotations

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.routes.shared import load_system_state, templates
from app.services.memory import (
    MemoryConflictError,
    accept_memory_candidate,
    archive_memory,
    archive_memory_candidate,
    create_memory,
    get_memory,
    get_memory_candidate,
    list_memories,
    list_memory_audit_events,
    list_memory_candidates,
    reject_memory_candidate,
    revise_memory,
)
from app.services.personal_scope import request_user_id


router = APIRouter(prefix="/memories")


def _audit_view(rows) -> list[dict]:
    events: list[dict] = []
    for row in rows:
        event = dict(row)
        try:
            details = json.loads(event["details_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            details = {}
        event["details"] = details if isinstance(details, dict) else {}
        events.append(event)
    return events


def _center_response(
    request: Request,
    *,
    status_code: int = 200,
    error: str | None = None,
    form_values: dict[str, str] | None = None,
):
    user_id = request_user_id(request)
    include_archived = request.query_params.get("state") == "all"
    with get_db() as db:
        context = {
            "memories": list_memories(
                db,
                include_archived=include_archived,
                user_id=user_id,
            ),
            "pending_candidates": list_memory_candidates(
                db,
                user_id=user_id,
            ),
            "audit_events": _audit_view(
                list_memory_audit_events(db, user_id=user_id)
            ),
            "system_state": load_system_state(db, user_id),
            "include_archived": include_archived,
            "notice": request.query_params.get("notice"),
            "error": error or request.query_params.get("error"),
            "form_values": form_values or {},
        }
    return templates.TemplateResponse(
        request=request,
        name="memory_center.html",
        context=context,
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def memory_center(request: Request):
    return _center_response(request)


@router.post("")
def create_manual_memory(
    request: Request,
    memory_type: str = Form(default=""),
    memory_key: str = Form(default=""),
    memory_value: str = Form(default=""),
    importance: str = Form(default="5"),
    source: str = Form(default="manual"),
    confidence: str = Form(default="1.0"),
    sensitivity: str = Form(default="normal"),
):
    user_id = request_user_id(request)
    form_values = {
        "memory_type": memory_type,
        "memory_key": memory_key,
        "memory_value": memory_value,
        "importance": importance,
        "source": source,
        "confidence": confidence,
        "sensitivity": sensitivity,
    }
    try:
        with get_db() as db:
            create_memory(
                db,
                memory_type=memory_type,
                memory_key=memory_key,
                memory_value=memory_value,
                importance=importance,
                source=source,
                confidence=confidence,
                sensitivity=sensitivity,
                user_id=user_id,
            )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("Secrets and banking information"):
            for field in ("memory_type", "memory_key", "memory_value", "source"):
                form_values[field] = ""
        return _center_response(
            request,
            status_code=422,
            error=message,
            form_values=form_values,
        )
    return RedirectResponse(url="/memories?notice=created", status_code=303)


@router.get("/{memory_id}/edit", response_class=HTMLResponse)
def edit_memory_page(request: Request, memory_id: int):
    user_id = request_user_id(request)
    with get_db() as db:
        memory = get_memory(db, memory_id, user_id=user_id)
        if memory is None or not memory["active"]:
            raise HTTPException(status_code=404, detail="Memory not found")
        history = db.execute(
            """
            SELECT * FROM memories
            WHERE user_id = ? AND memory_key = ? AND id != ?
            ORDER BY version DESC
            """,
            (user_id, memory["memory_key"], memory_id),
        ).fetchall()
        system_state = load_system_state(db, user_id)
    return templates.TemplateResponse(
        request=request,
        name="memory_edit.html",
        context={
            "memory": memory,
            "history": history,
            "system_state": system_state,
            "error": request.query_params.get("error"),
            "form_values": {},
        },
    )


@router.post("/{memory_id}/edit")
def update_manual_memory(
    request: Request,
    memory_id: int,
    expected_version: str = Form(default=""),
    memory_type: str = Form(default=""),
    memory_value: str = Form(default=""),
    importance: str = Form(default=""),
    source: str = Form(default=""),
    confidence: str = Form(default=""),
    sensitivity: str = Form(default=""),
):
    user_id = request_user_id(request)
    with get_db() as db:
        memory = get_memory(db, memory_id, user_id=user_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        try:
            revise_memory(
                db,
                memory_id,
                expected_version=expected_version,
                memory_type=memory_type,
                memory_value=memory_value,
                importance=importance,
                source=source,
                confidence=confidence,
                sensitivity=sensitivity,
                user_id=user_id,
            )
        except MemoryConflictError:
            return RedirectResponse(
                url="/memories?error=stale",
                status_code=303,
            )
        except ValueError as exc:
            history = db.execute(
                """
                SELECT * FROM memories
                WHERE user_id = ? AND memory_key = ? AND id != ?
                ORDER BY version DESC
                """,
                (user_id, memory["memory_key"], memory_id),
            ).fetchall()
            form_values = {
                "memory_type": memory_type,
                "memory_value": memory_value,
                "importance": importance,
                "source": source,
                "confidence": confidence,
                "sensitivity": sensitivity,
            }
            if str(exc).startswith("Secrets and banking information"):
                for field in ("memory_type", "memory_value", "source"):
                    form_values[field] = ""
            return templates.TemplateResponse(
                request=request,
                name="memory_edit.html",
                context={
                    "memory": memory,
                    "history": history,
                    "system_state": load_system_state(db, user_id),
                    "error": str(exc),
                    "form_values": form_values,
                },
                status_code=422,
            )
    return RedirectResponse(url="/memories?notice=updated", status_code=303)


@router.post("/{memory_id}/archive")
def archive_manual_memory(
    request: Request,
    memory_id: int,
    expected_version: str = Form(default=""),
):
    user_id = request_user_id(request)
    with get_db() as db:
        if get_memory(db, memory_id, user_id=user_id) is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        try:
            archive_memory(
                db,
                memory_id,
                expected_version=expected_version,
                user_id=user_id,
            )
        except MemoryConflictError:
            return RedirectResponse(
                url="/memories?error=stale",
                status_code=303,
            )
        except ValueError:
            return RedirectResponse(
                url="/memories?error=invalid",
                status_code=303,
            )
    return RedirectResponse(url="/memories?notice=archived", status_code=303)


def _require_candidate_for_request(db, candidate_id: int, user_id: int):
    candidate = get_memory_candidate(db, candidate_id, user_id=user_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Memory candidate not found")
    return candidate


@router.post("/candidates/{candidate_id}/accept")
def accept_candidate(request: Request, candidate_id: int):
    user_id = request_user_id(request)
    error = None
    with get_db() as db:
        _require_candidate_for_request(db, candidate_id, user_id)
        try:
            accept_memory_candidate(db, candidate_id, user_id=user_id)
        except ValueError as exc:
            error = str(exc)
    if error is not None:
        return _center_response(request, status_code=422, error=error)
    return RedirectResponse(url="/memories?notice=accepted", status_code=303)


@router.post("/candidates/{candidate_id}/reject")
def reject_candidate(
    request: Request,
    candidate_id: int,
    reason: str = Form(default=""),
):
    user_id = request_user_id(request)
    error = None
    with get_db() as db:
        _require_candidate_for_request(db, candidate_id, user_id)
        try:
            reject_memory_candidate(
                db,
                candidate_id,
                reason=reason,
                user_id=user_id,
            )
        except ValueError as exc:
            error = str(exc)
    if error is not None:
        return _center_response(request, status_code=422, error=error)
    return RedirectResponse(url="/memories?notice=rejected", status_code=303)


@router.post("/candidates/{candidate_id}/archive")
def archive_candidate(request: Request, candidate_id: int):
    user_id = request_user_id(request)
    error = None
    with get_db() as db:
        _require_candidate_for_request(db, candidate_id, user_id)
        try:
            archive_memory_candidate(db, candidate_id, user_id=user_id)
        except ValueError as exc:
            error = str(exc)
    if error is not None:
        return _center_response(request, status_code=422, error=error)
    return RedirectResponse(
        url="/memories?notice=candidate-archived",
        status_code=303,
    )
