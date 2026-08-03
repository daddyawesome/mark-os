from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import (
    IS_RAILWAY,
    SESSION_SECRET,
    is_authenticated,
    validate_auth_configuration,
)
from app.database import init_db
from app.routes import auth as auth_routes
from app.routes import checkins, goals, pages, quests

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
    version="0.2.2-phase4-revised",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

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


app.include_router(auth_routes.router)
app.include_router(checkins.router)
app.include_router(quests.router)
app.include_router(goals.router)
app.include_router(pages.router)
