# MARK OS

[![Tests](https://github.com/daddyawesome/mark-os/actions/workflows/tests.yml/badge.svg)](https://github.com/daddyawesome/mark-os/actions/workflows/tests.yml)

MARK OS is a personal and business operating system for turning real-world
priorities into clear quests. It combines a transparent daily-direction
engine, a quest/XP system, a Client Hunting CRM, and multi-user family/staff
workspaces — currently focused on one goal: help Mark and his brother find,
review, follow up with, and win clients.

```text
Find a lead → qualify the fit → choose the next outreach action
→ do the linked quest → move the pipeline → review results
```

## Full documentation

**[`PROJECT.md`](./PROJECT.md) is the canonical, detailed project
document** — product definition, architecture, database rules, roles and
permissions, the complete phase history, the current roadmap (through Phase
8), development/migration rules, and full local-setup instructions. Read it
before making non-trivial changes.

This README is intentionally short. If you're looking for anything beyond a
quick start, it's in `PROJECT.md`, not here.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set at minimum `MARK_OS_USERNAME`, `MARK_OS_PASSWORD`, and `SESSION_SECRET`
in `.env`, then run:

```bash
uvicorn --env-file .env app.main:app --reload
```

Open `http://127.0.0.1:8000`, the CRM at `/crm`, or check `/health`.

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1` or use
the existing `run.ps1` helper, which loads `.env` automatically when present.

## Tests

```bash
python -m pytest -q
```

Tests always use temporary SQLite databases — never `data/mark_os.db` or the
Railway volume. GitHub Actions runs the same command on every push and pull
request.

## Product principle

> Maximum awareness. Strong recommendations. Controlled autonomy.

MARK OS should become more capable without becoming less understandable.
