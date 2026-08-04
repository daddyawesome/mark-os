from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import (
    IS_RAILWAY,
    SESSION_SECRET,
    current_user,
    validate_auth_configuration,
)
from app.database import init_db
from app.routes import auth as auth_routes
from app.routes import checkins, client_hunting, goals, pages, quests, users
from app.services.access_control import can_access_request


BASE_DIR = Path(__file__).resolve().parent


def startup() -> None:
    # Refuse unsafe Railway configuration before opening or migrating SQLite.
    validate_auth_configuration()
    init_db()


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup()
    yield


app = FastAPI(
    title="MARK OS",
    version="0.3.0-client-hunting-mvp",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

PUBLIC_PATHS = {"/login", "/health"}


@app.middleware("http")
async def login_and_permission_guard(request: Request, call_next):
    path = request.url.path
    method = request.method.upper()

    # Templates can always inspect this state value, including public pages.
    request.state.current_user = None

    is_public = path in PUBLIC_PATHS or path.startswith("/static/")
    if is_public:
        return await call_next(request)

    user = current_user(request)
    if user is None:
        next_path = quote(path, safe="/")
        return RedirectResponse(
            url=f"/login?next={next_path}",
            status_code=303,
        )

    request.state.current_user = user

    if not can_access_request(user, method, path):
        if method in {"GET", "HEAD"}:
            return RedirectResponse(
                url="/crm?error=forbidden",
                status_code=303,
            )
        return PlainTextResponse(
            "Forbidden",
            status_code=403,
        )

    return await call_next(request)


# SessionMiddleware is added after the guard so it wraps the guard and makes
# request.session available before authentication and authorization checks.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="mark_os_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=IS_RAILWAY,
)

app.include_router(auth_routes.router)
app.include_router(checkins.router)
app.include_router(quests.router)
app.include_router(goals.router)
app.include_router(client_hunting.router)
app.include_router(users.router)
app.include_router(pages.router)
