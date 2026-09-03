from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.database import get_db
from app.routes.shared import load_system_state, templates
from app.services.data_portability import (
    build_portability_package,
    package_json,
    package_zip,
    table_csv,
)


router = APIRouter()


@router.get("/account/export", response_class=HTMLResponse)
def export_page(request: Request):
    with get_db() as db:
        package = build_portability_package(db, request.state.current_user)
        system_state = load_system_state(db)
    return templates.TemplateResponse(
        request=request,
        name="account_export.html",
        context={
            "system_state": system_state,
            "table_names": sorted(package["tables"]),
        },
    )


@router.get("/account/export/download")
def export_download(
    request: Request,
    format: str = "json",
    table: str | None = None,
):
    with get_db() as db:
        package = build_portability_package(db, request.state.current_user)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    normalized = format.strip().casefold()
    if normalized == "json":
        content, media_type, suffix = package_json(package), "application/json", "json"
    elif normalized == "zip":
        content, media_type, suffix = package_zip(package), "application/zip", "zip"
    elif normalized == "csv":
        if table not in package["tables"]:
            raise HTTPException(status_code=400, detail="Unknown or unavailable export table.")
        content = table_csv(package["tables"][table])
        media_type, suffix = "text/csv; charset=utf-8", f"{table}.csv"
    else:
        raise HTTPException(status_code=400, detail="Unsupported export format.")
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="mark-os-{stamp}.{suffix}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
