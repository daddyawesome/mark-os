# MARK-OS

MARK-OS is a personal and business operating system built with FastAPI, Jinja,
HTMX, Bulma, and SQLite. It combines private personal workspaces, quests and XP,
a multi-user CRM, staff workflows, organization-scoped business workspaces,
production safety, and optional budget-safe AI foundations.

The detailed architecture, roadmap, role model, database rules, release
procedures, backup/recovery runbooks, decision log, and current phase status live
in [`PROJECT.md`](PROJECT.md).

## Quick start

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Configure the required local values in `.env`, then start MARK-OS:

```bash
uvicorn --env-file .env app.main:app --reload
```

Useful local pages:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/crm
http://127.0.0.1:8000/health
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
