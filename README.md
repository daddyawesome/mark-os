# MARK-OS

MARK-OS is a personal and business operating system built with FastAPI, Jinja,
HTMX, Bulma, and SQLite. It combines a private personal workspace (goals,
quests, XP, check-ins), a multi-user client-hunting CRM, organization-scoped
business workspaces for running more than one venture from one deployment,
staff roles and approval workflows, and production safety (backups,
observability, optimistic edit protection) — with AI kept optional and
budget-safe rather than load-bearing.

**Status:** actively developed, in production on Railway. Current phase:
Phase 6 (Agency Operations and Production Safety) — see
[`PROJECT.md`](PROJECT.md) for exactly what's shipped versus in progress.

The detailed architecture, role model, database rules, release procedures,
backup/recovery runbooks, decision log, and full phase-by-phase roadmap live
in [`PROJECT.md`](PROJECT.md). This file only covers what you need to run the
project locally.

## Quick start

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set at least `MARK_OS_USERNAME` and `MARK_OS_PASSWORD` in `.env` — MARK-OS does
not load `.env` automatically, so always pass it explicitly to Uvicorn:

```bash
uvicorn --env-file .env app.main:app --reload
```

`SESSION_SECRET` is only required when deploying on Railway; a dev default is
used locally, and startup will refuse to run on Railway without a real one.
See `.env.example` for the full list of optional variables (custom DB path,
backup settings, health-check monitoring).

Useful local pages:

```text
http://127.0.0.1:8000/        personal workspace / quests
http://127.0.0.1:8000/crm     client-hunting CRM
http://127.0.0.1:8000/health  liveness + DB check, used by Railway and uptime monitoring
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn --env-file .env app.main:app --reload
```

## Tests

Run the complete suite:

```bash
python -m pytest -q
```

Tests must use isolated temporary databases and must never point at the Railway
production volume.

## Documentation

- [`PROJECT.md`](PROJECT.md) — canonical product guide, roadmap, architecture,
  operations, release, backup, and recovery documentation.
- [`AGENTS.md`](AGENTS.md) — repository instructions for coding agents.
- [`.agents/skills/`](.agents/skills/) — project-specific UI and HTMX rules.
- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) — third-party attribution
  and design-inspiration notices.

Do not create new phase-specific roadmap or handoff Markdown files. Add durable
project information to `PROJECT.md` instead.

## Safety

Do not commit `.env`, passwords, session secrets, SQLite database files,
generated backups, release-evidence folders, private playbooks, rclone tokens,
or other credentials.
