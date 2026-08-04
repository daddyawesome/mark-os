# MARK OS — Client Hunting MVP

[![Tests](https://github.com/daddyawesome/mark-os/actions/workflows/tests.yml/badge.svg)](https://github.com/daddyawesome/mark-os/actions/workflows/tests.yml)

MARK OS is a personal operating system for turning real-world priorities into
clear quests. Its current product focus is practical and narrow: help Mark find,
prioritize, contact, and win clients.

The operating loop is:

```text
Find a lead → qualify the fit → choose the next outreach action
→ do the linked quest → move the pipeline → review results
```

## Current status

The Client Hunting CRM is the active business track. Phase 5 memory work pauses
after the persistent-chat and agent-audit foundations so the product can first
help create revenue.

| Track | Status | What exists |
| --- | --- | --- |
| MARK OS v0.1 foundation | Complete | SQLite profile, goals, projects, check-ins, history, and transparent direction logic |
| Secure web and Life OS foundation | Complete | Login protection, Railway-safe session configuration, modular routes, and Life OS views |
| Phase 4 — Quest Engine | Complete | Quest lifecycle, progress, blockers, evidence, immutable XP awards, levels, and timeline events |
| Phase 5.1 — Persistent Chat | Complete | Additive chat storage, session/message lifecycle, recent history, and duplicate-request protection |
| Phase 5.2 — Agent Audit | Complete | Persistent agent runs and steps, usage/cost estimates, lifecycle tracking, idempotency, and safe error summaries |
| Client Hunting C1–C4 — CRM MVP | Complete | Lead storage, quest linkage, CRUD, pipeline, priority, next actions, duplicate prevention, and dashboard |
| Client Hunting C5 — Railway release | Complete | Production volume mounted, startup migration completed, health verified, and CRM routes live |
| Phase 5.3 — Structured Memory | Paused | Next memory step after the Client Hunting MVP proves useful |
| Phase 5.4+ — AI and integrations | Planned | Memory extraction, retrieval, AI routing, Neo4j, LangGraph, Gmail, and Calendar remain deferred |

## Client Hunting CRM

Open `/crm` to record and manage:

- company and contact person;
- job title;
- source and source link;
- the client problem or opportunity;
- why Mark is a strong fit;
- pipeline status and priority;
- the next outreach action, due date, and notes.

Pipeline stages are:

```text
New → Reviewed → Contacted → Replied → Meeting → Proposal → Won / Lost
```

Priorities are `High`, `Medium`, and `Low`.

The dashboard shows total leads, high-priority leads, contacted leads, replies,
meetings, proposals, and won clients.

### Every lead is a quest

Creating a lead atomically creates one linked Client Hunting quest. The quest
title, priority, due date, reason, progress, and lifecycle follow the lead's
current pipeline and next action. Won and lost leads use a reversible CRM
`closed` quest state rather than the Quest Engine's immutable XP completion.
CRM transitions never award or reverse XP, so correcting a mistaken pipeline
entry cannot corrupt the XP ledger.

Removing a mistaken or duplicate lead is confirmation-protected and reversible
at the data level: the lead is hidden from active CRM views and its linked quest
is abandoned instead of destroying quest, XP, or timeline history.

Duplicate protection uses a request key plus an immutable creation fingerprint
for exact retries, and a normalized identity derived from company, contact, and
source information for semantic duplicates.

## Existing MARK OS capabilities

- Daily check-ins for cash movement, expenses, free time, energy, progress, and blockers.
- A transparent Director that recommends one main quest and supporting actions.
- Goals, projects, quests, progress updates, completion evidence, XP, and levels.
- Persistent chat and agent-audit storage foundations without paid AI calls.
- Safe additive SQLite startup migrations with legacy-data regression tests.
- Single-user authentication suitable for Mark's private deployment.

## Project structure

```text
app/
├── auth.py
├── database.py              # stable connection/initialization facade
├── db/
│   ├── agent_audit.py       # agent audit schema and validation
│   ├── chat.py              # persistent chat schema and validation
│   ├── checkins.py          # check-in and direction migrations
│   ├── goals.py             # profile, goal, and project migrations
│   ├── leads.py             # CRM schema, migration, and validation
│   ├── memory.py            # timeline, memory, and system metadata
│   ├── migrations.py        # ordered cross-domain migration runner
│   ├── quests.py            # quest, game state, and XP migrations
│   └── schema.py            # hardcoded migration helpers
├── main.py
├── routes/
│   ├── auth.py
│   ├── checkins.py
│   ├── client_hunting.py
│   ├── goals.py
│   ├── pages.py
│   └── quests.py
├── services/
│   ├── agent_audit.py
│   ├── chat.py
│   ├── director.py
│   ├── gamification.py
│   ├── lead_identity.py
│   ├── leads.py
│   └── quests.py
└── templates/
    ├── client_hunting.html
    ├── lead_detail.html
    ├── edit_lead.html
    └── delete_lead.html

tests/
├── test_application.py
├── test_crm_migrations.py
├── test_leads.py
└── ...
```

## Local setup

Create a virtual environment, install the existing dependencies, and copy the
documented environment variables:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `MARK_OS_PASSWORD` and `SESSION_SECRET` in `.env`, then run:

```bash
uvicorn --env-file .env app.main:app --reload
```

Open `http://127.0.0.1:8000/crm`. The health endpoint is
`http://127.0.0.1:8000/health`.

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1` or use the
existing `run.ps1` helper, which loads `.env` automatically when the file exists.

## Tests

Tests always use temporary SQLite databases; they must never target
`data/mark_os.db` or the Railway volume.

```bash
python -m pytest -q
```

Coverage includes fresh and legacy migrations, preserved quest/XP/check-in/
memory data, lead CRUD, duplicate protection, quest linkage, pipeline syncing,
dashboard totals, authentication, and application startup. GitHub Actions runs
the same command on every push and pull request.

## Railway release safety

The Client Hunting MVP is live on Railway. Every future release remains an
explicit separate step. Before deployment:

1. review, test, and commit the release changes;
2. back up the persistent SQLite volume;
3. confirm `MARK_OS_USERNAME`, `MARK_OS_PASSWORD`, `SESSION_SECRET`, and the
   persistent `MARK_OS_DB_PATH`;
4. approve the push/deploy;
5. verify `/health`, `/crm`, one test lead, its linked quest, and the dashboard.

External email, scraping, paid AI calls, Neo4j, embeddings, and calendar
integrations remain outside the CRM MVP.

## Product principle

> Maximum awareness. Strong recommendations. Controlled autonomy.


## Family workspaces — M10

MARK OS now supports three isolated roles:

- **Owner** — full personal OS, Client Hunting CRM, and family account management.
- **Member** — a private dashboard, goals, projects, quests, check-ins, XP,
  history, memories, and chat; no CRM or account-administration access.
- **Lead sourcer** — the narrow Client Hunting CRM surface only.

Each owner/member receives one private profile and game state. New member
workspaces otherwise begin blank. All personal reads and writes are scoped by
`user_id`, cross-user resource IDs return `404`, and database triggers enforce
parent/child ownership. Project names and memory keys are unique per user, so
family members may independently reuse the same labels without collisions.
