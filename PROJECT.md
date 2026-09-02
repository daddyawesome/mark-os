# MARK-OS — Complete Project Guide and Roadmap

**Canonical project document**
**Repository:** `https://github.com/daddyawesome/mark-os`
**Reviewed against `main`:** 2026-08-08
**Current active phase:** Phase 6 — Agency Operations and Production Safety
**Immediate next milestone:** Deploy Phase 6.6C and finish Pendang real-user acceptance
**Production deployment:** Railway
**Primary database:** SQLite on a persistent Railway volume
**Last verified full-suite baseline:** 531 passed after Phase 6.6C Pendang Company Knowledge and Marketing

## Current status: Phase 6.6 / 6.7

Phase 6.6 (Bulk Lead Management and CRM Workspaces) is implemented in full,
substeps 6.6A through 6.6F. Phase 6.7 (Outreach Templates and Approval
Controls) is also implemented. All are locally complete and test-verified;
production acceptance for the Pendang-facing surfaces remains the outstanding
gate.

| Substep | What it added | Status |
|---|---|---|
| 6.6A | Bulk lead CSV preview | ✅ Complete |
| 6.6B-1 | `organizations` / `organization_memberships` tables, seeded `mark-agency` and `pendang` workspaces | ✅ Complete |
| 6.6B-4A | Workspace-scoped lead dedupe and core CRM service boundary | ✅ Complete |
| 6.6B-4B | Active workspace propagated through every runtime CRM route | ✅ Complete |
| 6.6B-5 | Revocable Pendang staff membership authority | ✅ Complete |
| 6.6B-6 | Workspace switching UI, Pendang launch surface, forced password rotation | ✅ Complete |
| 6.6B-7 | Optimistic `row_version` edit protection on leads | ✅ Complete |
| 6.6B-8A | Release-verification harness (`tools/verify_phase_6_6b_release.py`) with rehearsal backup/restore | ✅ Complete |
| 6.6B-8B | Production-copy migration rehearsal | ⏳ Required before Rey/Freddy onboarding |
| 6.6C | `/pendang` company home: organization-scoped company knowledge, services/pricing, case studies, content drafts | ✅ Implementation complete locally — production acceptance required |
| 6.6D | Selective CSV row import with permission-scoped researcher/BD-owner assignment | ✅ Complete |
| 6.6E | Bulk research submission for review, permission-scoped CSV/JSON export, approved-leads export | ✅ Complete |
| 6.6F | Owner-only downloadable full-database backup; release verifier extended to the 6.6C Pendang company-knowledge boundary | ✅ Complete |
| 6.7 | Owner/workspace-owner-authored, approval-gated outreach templates with safe `{{variable}}` preview rendering for Relationship Managers | ✅ Complete |

**Outstanding before Pendang is operationally complete:**
- Run `tools/verify_phase_6_6b_release.py` against a real Railway production-DB copy (6.6B-8B).
- Deploy the additive 6.6C–6.7 migrations through the standard Railway release process; confirm `/health`.
- Rey and Freddy replace their temporary passwords and land on `/pendang`.
- Smoke-test Rey's company-content write authority and Freddy's read-only view.
- Complete real Pendang lead/review/next-action acceptance gates.

Full substep-by-substep implementation notes for 6.6B-1 through 6.6B-8A live in
the [Decision Log](#19-decision-log) and git history; they are intentionally
not repeated here now that each substep is complete and superseded by the next.

### Phase 6.6D–F and 6.7 implementation notes

- **6.6D — Selective import.** `import_leads_from_csv` now accepts
  `selected_row_numbers` (rows not selected are reported as `skipped_count`,
  never written) and an optional `researcher_user_id`, validated against
  active Lead Sourcers in the workspace and applied as `assigned_to_user_id`
  so that sourcer immediately gains visibility through the existing
  `_actor_matches_lead` rule. The CSV preview page now carries the previewed
  file forward as a hidden base64 field, renders a checkbox per valid row,
  and — only for actors with CRM owner authority — optional researcher /
  Business Development Owner dropdowns scoped to the active workspace.
- **6.6E — Bulk submission and export.** `bulk_submit_research_for_review`
  reuses the single-lead `submit_research_for_review` per lead so
  permission/state failures on one lead never block or corrupt the rest of
  the batch; the CRM dashboard's lead table gained sourcer-only checkboxes
  and a bulk "Submit selected for review" action. `app/services/lead_export.py`
  reuses the existing `list_visible_leads` role/organization visibility query
  for CSV and JSON export (`GET /crm/leads/export?format=&scope=`), with
  spreadsheet-formula-injection neutralization on exported text cells and an
  `approved`-only scope for approved-leads export.
- **6.6F — Downloadable backup and verifier extension.** `GET
  /crm/backup/download` (global Owner only — the backup spans every
  workspace) creates a fresh online SQLite backup via the existing
  `database_backup` service and streams it. While wiring this up, two
  pre-existing Windows-only bugs in `app/services/database_backup.py` were
  found and fixed: `verify_sqlite_database` was never closing its read-only
  connection (`with connection:` only commits/rolls back, it does not
  close), and `_atomic_write_text` reopened its just-written manifest file
  in read-only mode to `fsync` it, which Windows rejects. Both are fixed
  with an explicit `contextlib.closing()` and a single write-mode handle
  respectively; this also fixed 8 pre-existing Windows-only failures in
  `tests/test_database_backup.py` and `tests/test_phase_6_6b_release_verifier.py`
  that predate this work. `tools/verify_phase_6_6b_release.py` now also
  asserts the Phase 6.6C boundary: exactly one Pendang company profile,
  exactly four active Pendang service seed items, and zero Pendang
  company-knowledge rows under MARK Agency.
- **6.7 — Outreach templates.** New `outreach_templates` table
  (workspace-scoped, additive) seeded with six draft, unapproved starter
  templates per workspace using only generic `{{variable}}` wording — no
  invented client, pricing, or relationship content. `app/services/outreach_templates.py`
  gates create/update/approve/archive behind `has_crm_owner_authority`
  (global Owner or Pendang workspace-owner authority) with optimistic
  `row_version` protection; `render_template` is a fixed regex substitution
  over `{{name}}` tokens only (never a template-engine `.render()` call over
  Owner-authored text), leaving unresolved placeholders visible rather than
  blank. Relationship Managers can list and render only `approved` templates
  at `/crm/templates` and `/crm/templates/{id}/use`; the preview page has a
  copy-to-clipboard button and no send action of any kind. Template usage is
  intentionally not auto-logged — the existing Phase 6.3 lead-activity form
  remains the place staff record that outreach happened.

---

## 1. Purpose of This Document

This file is the single source of project documentation for MARK-OS.

It consolidates and supersedes the detailed content previously spread across:

Use this file to understand:

- what MARK-OS is;
- what has already been implemented;
- how the current repository is structured;
- how the database and permissions work;
- what is safe to change;
- how to run and test the project;
- the complete historical phase record;
- the current roadmap;
- the future agency, product-hardening, and AI plans.

When the project changes, update this file instead of creating another
standalone roadmap, install guide, release runbook, or handoff document.

---

## 2. Product Definition

MARK-OS is a personal and business operating system.

It combines:

```text
Database
+ personal workspace
+ quests
+ client-hunting CRM
+ family and staff accounts
+ review
+ memory
+ deterministic recommendations
+ budget-safe AI foundations
+ safety and auditability
```

The product is not only an AI chat page.

Its purpose is to help Mark:

- turn priorities into clear quests;
- track work, progress, blockers, evidence, XP, and outcomes;
- manage goals, projects, check-ins, history, and personal direction;
- find and qualify client opportunities;
- coordinate lead research with his brother;
- coordinate relationship development with Junmar;
- build repeatable outreach and follow-up discipline;
- preserve important decisions and lessons;
- eventually operate the full agency lifecycle;
- remain useful without paid AI.

### Product principle

> Maximum awareness. Strong recommendations. Controlled autonomy.

### Business goal

MARK-OS should support progress toward at least:

```text
USD 10,000 per month
```

The shortest-term business focus is not advanced AI. It is a usable agency
workflow that helps Mark, his Lead Researcher, and his Relationship Manager
consistently find, review, contact, and convert leads while protecting production data.

---

## 3. Core Architecture Principle

MARK-OS must never depend on an AI provider as its source of truth.

```text
SQLite database = operational truth
Python services = rules, validation, and permissions
HTMX/Bulma = user interface
Deterministic Director = explainable recommendations
AI provider = optional reasoning and communication
Vector search = optional semantic recall
Graph database = optional relationship recall
```

The application must remain useful when:

- no AI provider is configured;
- the AI provider is unavailable;
- the monthly AI budget is exhausted;
- embeddings have not been generated;
- a future graph database is offline.

---

## 4. Current Technology Stack

| Layer | Current implementation |
|---|---|
| Backend | FastAPI |
| Server-rendered interaction | HTMX |
| UI framework | Bulma |
| Frontend customization | Jinja templates, static CSS, static JavaScript |
| Operational database | SQLite |
| Deployment | Railway |
| Persistent storage | Railway volume |
| Authentication | Database-backed user accounts and sessions |
| Password storage | Password hashes |
| Authorization | Role-based request access plus user-scoped data services |
| Source control | GitHub |
| Testing | Pytest and GitHub Actions |
| Local development | macOS and Windows |
| Python environment | `.venv` |

### Future optional technologies

These are not required for the current agency phase:

| Capability | Planned option |
|---|---|
| Semantic retrieval | SQLite + `sqlite-vec` |
| Production vector upgrade | PostgreSQL + `pgvector` |
| Graph memory | Neo4j AuraDB Free |
| Controlled workflow | LangGraph |
| Local AI development | Ollama |
| Remote AI | Provider abstraction with environment-configured models |

Do not replace SQLite with Neo4j.

Do not introduce another web framework or ORM without a documented reason.

---

## 5. Current Repository Review

The current repository is no longer single-user.

The older documentation that described MARK-OS as private single-user software
is historical and has been superseded by the M7–M10 family workspace work.

### Current top-level structure

```text
mark-os/
├── .github/
│   └── workflows/
├── app/
│   ├── db/
│   ├── routes/
│   ├── services/
│   ├── static/
│   ├── templates/
│   ├── auth.py
│   ├── database.py
│   └── main.py
├── data/
├── tests/
├── .agents/
├── AGENTS.md
├── PROJECT.md
├── README.md
├── THIRD_PARTY_NOTICES.md
├── .env.example
├── .gitignore
├── railway.json
├── requirements.txt
└── run.ps1
```

### Current database modules

```text
app/db/
├── agent_audit.py
├── chat.py
├── checkins.py
├── family_integrity.py
├── family_ownership.py
├── family_workspace.py
├── goals.py
├── lead_activities.py
├── leads.py
├── memory.py
├── migrations.py
├── playbooks.py
├── quests.py
├── relationship_manager.py
├── schema.py
└── users.py
```

### Current route modules

```text
app/routes/
├── auth.py
├── checkins.py
├── client_hunting.py
├── family.py
├── goals.py
├── pages.py
├── quests.py
├── relationship_manager.py
├── shared.py
└── users.py
```

### Current service modules

```text
app/services/
├── access_control.py
├── agent_audit.py
├── chat.py
├── director.py
├── error_summary.py
├── follow_up_command_center.py
├── gamification.py
├── lead_activities.py
├── lead_csv_import.py
├── lead_identity.py
├── lead_pipeline_workflow.py
├── lead_research_permissions.py
├── lead_research_workflow.py
├── lead_work_queues.py
├── leads.py
├── observability.py
├── operations_monitoring.py
├── passwords.py
├── personal_scope.py
├── playbooks.py
├── quests.py
├── relationship_manager.py
├── security.py
├── team_users.py
└── users.py
```

### Current test areas

The repository contains tests for:

- application routes;
- authentication;
- database authentication;
- users and user migrations;
- role permissions;
- security hardening;
- family-member foundation;
- family data ownership;
- family isolation;
- family workspace release;
- lead ownership;
- CSV lead import;
- CRM migrations;
- Lead Activity Timeline schema and migration;
- Lead Activity Timeline service and permissions;
- Lead Activity Timeline routes and UI;
- Atomic Contacted transition and rollback behavior;
- Follow-up Command Center queue calculations, filters, role scope, and Manila boundaries;
- Follow-up Command Center route, filters, queue rendering, empty states, and navigation;
- Follow-up Command Center acceptance isolation, exact Manila cutoffs, read-only behavior, and complete empty-state rendering;
- structured application logging, correlation IDs, safe exception handling, and security-event summaries;
- database-aware health responses, external uptime checks, backup visibility, and optional Owner webhook alerts;
- bounded previous-24-hour structured error summaries, Railway wrappers, safe samples, and exact UTC boundaries;
- responsive CRM hero layout, action wrapping, desktop sidebar widths, mobile stacking, and stylesheet cache busting;
- lead behavior;
- chat;
- chat migrations;
- agent audit;
- agent-audit migrations;
- quests;
- gamification;
- memory migrations;
- Director behavior;
- sidebar and user navigation;
- Lead Researcher workflow and permissions;
- Relationship Manager workflow, private playbooks, and CRM isolation;
- role-aware CRM queues;
- staging-copy release verification.

---

## 6. Current Roles and Access

The backend role values are:

```text
owner
member
lead_sourcer
relationship_manager
```

Displayed agency titles:

```text
lead_sourcer          → Lead Researcher
relationship_manager → Business Development Collaborator / Relationship Manager
```

### 6.1 Owner

Mark is the Owner and Founder/Admin.

Current access:

- full personal MARK-OS workspace;
- goals, projects, quests, check-ins, XP, history, memory, and chat;
- complete Client Hunting CRM access;
- research review and outreach approval;
- pipeline, proposal, Won/Lost, assignment, and archive decisions;
- Relationship Manager assignment;
- user and playbook administration;
- family-member and staff-account administration;
- all owner-only settings and maintenance actions.

### 6.2 Member

A family member receives a private personal workspace.

Current access:

- private dashboard and profile;
- own goals, projects, quests, and check-ins;
- own XP, history, memory, and chat.

A Member must not access:

- Client Hunting CRM;
- playbook or staff operations;
- user administration;
- another user's personal records.

### 6.3 Lead Sourcer / Lead Researcher

This role is narrow and CRM-only.

Current access:

- CRM dashboard and role-aware research queues;
- create and import leads;
- view created, assigned, or researched leads;
- edit permitted research fields;
- submit work for review;
- respond to requested changes;
- read Owner review decisions.

This role cannot:

- approve research or outreach;
- change major pipeline stages;
- mark Won or Lost;
- delete leads;
- access private personal or family workspaces;
- manage users or system settings.

### 6.4 Relationship Manager / Business Development Collaborator

This role is also CRM-only and has a dedicated landing page:

```text
/relationship-manager
```

Current access:

- assigned private sales playbook;
- relationship-work queues and scorecard;
- create and import qualified leads;
- view leads created by or assigned to the user as Business Development Owner;
- read research and outreach-approval status;
- update permitted next actions and due dates;
- prepare relationship work and hand interested prospects to Mark.

This role cannot:

- access Mark's or family members' private workspace;
- edit or approve Lead Researcher work;
- approve outreach;
- change pipeline stages;
- set pricing, scope, discounts, or delivery promises;
- create proposals or mark Won/Lost;
- archive leads;
- manage users or system settings.

The `Contacted` transition is Owner-controlled and now writes its required
activity audit atomically. Phase 6.13 remains the separate gate for explicit,
revocable delegated outreach.

---

## 7. Current Multi-User Data Isolation

M8–M10 added personal `user_id` ownership to private data.

Personal data includes:

```text
profile
goals
projects
checkins
directions
game_state
game_history
tasks
quest_updates
xp_ledger
memories
timeline_events
chat_sessions
chat_messages
agent_runs
agent_steps
```

Current rules:

- personal reads and writes are scoped to the authenticated user;
- cross-user private IDs return `404`;
- Owner sees the Owner's own private data, not every family member's private
  workspace by default;
- Members see only their own private data;
- Lead Researchers and Relationship Managers do not receive personal workspace access;
- ownership triggers protect parent/child relationships;
- project names are unique per user;
- memory keys are unique per user;
- each Owner or Member receives one private profile and one game state.

CRM leads use separate collaboration and workflow fields:

```text
created_by_user_id
assigned_to_user_id
researched_by_user_id
business_development_owner_user_id
research_status
submitted_for_review_at
reviewed_by_user_id
reviewed_at
review_notes
outreach_approved_by_user_id
outreach_approved_at
```

These fields represent different responsibilities and must not be overloaded.
Personal workspace ownership remains separate from CRM collaboration.

---

## 8. Current Database and Operational Rules

The configured SQLite path is resolved from:

```text
MARK_OS_DB_PATH
```

The local default is normally:

```text
data/mark_os.db
```

Railway must use a path inside the mounted persistent volume.

### Existing operational domains

#### Users and sessions

The `users` table includes:

- username;
- display name;
- password hash;
- role;
- active status;
- must-change-password flag;
- session version;
- last-login timestamp;
- creation and update timestamps.

Session versioning supports revocation when an account is deactivated or its
password is reset.

#### Profile

Stores one private profile per Owner or Member, including:

- name;
- wealth goal;
- weekday hours;
- weekend rule;
- strongest skills;
- primary blocker.

#### Goals

Stores long-term personal goals with:

- title;
- category;
- status;
- priority;
- ownership;
- timestamps.

#### Projects

Stores:

- name;
- purpose;
- status;
- priority;
- progress;
- next action;
- optional goal relationship;
- ownership;
- timestamps.

Project names are unique within one user's workspace, not globally.

#### Check-ins

Stores daily check-ins, including:

- date;
- `cash_in`;
- expenses;
- free hours;
- energy;
- accomplishment;
- blocker;
- notes;
- ownership;
- timestamps.

Business rule:

```text
cash_in adds to available cash
expenses subtract from available cash
```

#### Directions

Stores deterministic Director output associated with a check-in:

- main quest;
- reason;
- side quests;
- what to avoid;
- success signal;
- ownership.

#### Game state and history

Stores:

- level;
- total XP;
- XP into current level;
- class;
- threshold mode;
- source;
- notes;
- level/game events;
- ownership.

#### Quests

The `tasks` table is the Quest Engine's main table.

It stores:

- owner;
- optional project and goal relationships;
- title and description;
- status;
- priority;
- estimated time;
- actual time;
- energy required;
- due date;
- difficulty;
- XP reward;
- progress;
- quest source;
- why;
- blocked reason;
- result notes;
- evidence;
- start, completion, creation, and update timestamps.

#### Quest updates

Stores append-only progress history:

- progress percentage;
- notes;
- session minutes;
- blocker reason;
- event type;
- timestamps;
- ownership.

#### XP ledger

Stores immutable XP events.

Quest-completion XP must be awarded exactly once.

#### Memories

Current memory storage includes legacy and structured-memory foundations.

Important rules:

- memory belongs to a user;
- memory keys are unique per user;
- existing memory columns must be migrated additively;
- secrets and unnecessary confidential information must not be stored;
- important source records should not be duplicated into memory without a
  clear reason.

#### Timeline events

Stores meaningful dated events and structured details.

#### Chat

Existing tables:

```text
chat_sessions
chat_messages
```

Current capabilities include:

- session and message storage;
- recent-history loading;
- duplicate-request protection;
- user ownership;
- foundations for rename/edit/delete behavior.

#### Agent audit

Existing tables:

```text
agent_runs
agent_steps
```

Current capabilities include:

- lifecycle status;
- provider and model fields;
- token and cost estimates;
- step tracking;
- safe error summaries;
- idempotency and audit foundations;
- user ownership.

#### Playbooks and relationship management

Current tables:

```text
playbooks
user_playbook_assignments
```

Current rules:

- internal Markdown is imported into SQLite rather than committed publicly;
- playbooks are assigned to specific active users;
- rendered Markdown is escaped safely;
- Relationship Manager queues are scoped by Business Development ownership;
- playbook and CRM access do not grant private personal-workspace access.

#### Outreach templates

Current table:

```text
outreach_templates
```

Current rules:

- workspace-scoped (`organization_id`), never shared across `mark-agency`
  and `pendang`;
- create/update/approve/archive require `has_crm_owner_authority`
  (global Owner or Pendang workspace-owner authority);
- Relationship Managers may only list and render `approved = 1` rows;
- rendering is a fixed `{{variable}}` regex substitution, never a
  template-engine `.render()` call over stored text;
- optimistic `row_version` protection on every write;
- seeded starter content is intentionally generic and unapproved by
  default — Mark must review and approve before it reaches a
  Relationship Manager.

#### CRM leads

The current lead schema includes:

```text
id
quest_id
created_by_user_id
assigned_to_user_id
researched_by_user_id
business_development_owner_user_id
research_status
submitted_for_review_at
reviewed_by_user_id
reviewed_at
review_notes
outreach_approved_by_user_id
outreach_approved_at
request_key
request_fingerprint
dedupe_key
company
contact_person
job_title
source
source_url
problem_opportunity
why_mark_fits
pipeline_status
priority
next_action
next_action_due_date
notes
created_at
updated_at
deleted_at
```

Pipeline stages:

```text
New
→ Reviewed
→ Contacted
→ Replied
→ Meeting
→ Proposal
→ Won / Lost
```

Stored backend values:

```text
new
reviewed
contacted
replied
meeting
proposal
won
lost
```

Priorities:

```text
high
medium
low
```

---

## 9. Current Client Hunting CRM

The current CRM records:

- company;
- contact person;
- job title;
- source;
- source URL;
- problem or opportunity;
- why Mark fits;
- pipeline status;
- priority;
- next action;
- next-action due date;
- notes;
- creator;
- assignee;
- researcher and research-review state;
- outreach approval;
- Business Development Owner.

### Every lead is linked to a quest

Creating a lead creates one linked Client Hunting quest in the same operation.

The linked quest follows:

- lead priority;
- lead due date;
- lead next action;
- lead pipeline progress;
- lead lifecycle.

Won and Lost are reversible CRM outcomes.

They do not use the Quest Engine's immutable completion/XP path, so correcting
a CRM status does not corrupt the XP ledger.

### Duplicate protection

Current duplicate protection uses:

- request keys for network/idempotency retries;
- immutable request fingerprints;
- normalized semantic identity from company, contact, source, and source URL;
- an active-lead unique deduplication key.

### Deletion behavior

Current lead deletion is soft deletion through `deleted_at`.

The linked quest is abandoned rather than permanently destroying quest, XP, or
timeline history.

---

## 10. Current Agency Operations Status

### Completed operational foundation

| Capability | Status |
|---|---|
| Owner, Member, Lead Researcher, and Relationship Manager accounts | Complete |
| Private family data isolation | Complete |
| CRM creator, assignee, researcher, and Business Development ownership | Complete |
| Lead research edit and review workflow | Complete |
| Changes-requested resubmission | Complete |
| Owner research and outreach approval | Complete |
| Owner-only pipeline gates | Complete |
| Role-aware CRM queues | Complete |
| Private playbook storage and assignment | Complete |
| Relationship Manager landing page | Complete |
| Direct-URL and forged-request protection | Complete |
| Staging-copy release verification and rollback runbook | Complete foundation |

### Immediate operational gaps

This table predates several now-complete phases; it is left largely as
written historically except for the rows this session's work closes. See
[Current status: Phase 6.6 / 6.7](#current-status-phase-66--67) for the
authoritative, up-to-date picture — Phase 6.2, 6.4, 6.5, and 6.6B are
already ✅ Complete per the [Phase Completion Log](#18-phase-completion-log)
even though they still appear below as "next phase" rows.

| Requirement | Next phase |
|---|---|
| Tested production backup and restore process | Phase 6.2 |
| Due, overdue, waiting, and stale-lead command center | Phase 6.4 |
| Production health and error alerts | Phase 6.5 |
| Safe bulk preview, assignment, import, and export | ✅ Implemented (Phase 6.6, all substeps) |
| Pendang CRM workspace and staff launch | Phase 6.6B |
| Deterministic approved outreach templates | ✅ Implemented (Phase 6.7) |
| Research effort and webhook intake | Phase 6.8 |
| Discovery, proposal, onboarding, and billing workflows | Trigger-based Phases 6.9–6.12 |
| Delegated Relationship Manager outreach | Trigger-based Phase 6.13 |

The next priority is production acceptance of Phases 6.6 and 6.7: the
6.6B-8B production-copy rehearsal, the Railway deploy of the accumulated
additive migrations, and the real Rey/Freddy onboarding and lead-acceptance
gates described above. No further implementation work is required to reach
that gate.

---

# 11. Historical Phase Record

## Phases 1–3 — Foundation

**Status:** Complete

Completed foundations include:

- FastAPI application;
- SQLite database;
- HTMX and Bulma UI;
- authentication;
- modular routes and services;
- goals, projects, check-ins, history, and direction;
- Railway deployment and health checking.

## Phase 4 — Revised Quest Engine

**Status:** Complete

### Definition of done

#### Quest lifecycle

- create;
- open;
- start;
- block;
- unblock;
- abandon;
- complete.

#### Progress history

- append-only updates;
- progress percentage;
- notes;
- session minutes;
- blocker reason;
- timestamps.

#### Completion

- completion result required;
- optional evidence;
- completion timestamp;
- timeline event.

#### XP

- immutable ledger;
- one XP award per completion event;
- database-level unique event protection;
- refresh or duplicate submission cannot award XP twice.

#### Leveling

- current level retained;
- imported Level 3 state preserved;
- one reward may cross multiple level thresholds;
- level-up history recorded.

#### AI readiness

- Director is aware of open quests;
- quest outcomes can later become memory candidates;
- chat tools must use quest service functions rather than raw SQL.

## Phase 5.1 — Persistent Chat

**Status:** Complete

Implemented foundations:

- chat sessions;
- chat messages;
- recent-history loading;
- complete SQLite history;
- duplicate-request protection;
- user ownership;
- history lifecycle foundations.

## Phase 5.2 — Agent Audit

**Status:** Complete

Implemented foundations:

- agent runs;
- agent steps;
- status tracking;
- provider/model fields;
- usage and cost estimates;
- lifecycle timestamps;
- idempotency;
- safe error summaries;
- user ownership.

## M1–M10 — Multi-User and Family Release

**Status:** Complete

Main outcomes:

- database-backed accounts;
- password hashing;
- role permissions;
- lead ownership;
- account administration;
- session security;
- family member role;
- family data ownership;
- per-user service and route isolation;
- private member workspaces;
- per-user uniqueness;
- sidebar and Users navigation.


## Phase 6.1A–6.1I — Staff Research, Review, Approval, and Release Safety

**Status:** Complete

Main outcomes:

- research ownership and workflow states;
- Lead Researcher edit and resubmission flow;
- Owner review, outreach approval, and pipeline gates;
- role-aware CRM queues;
- service-side permissions and forged-request tests;
- staging-copy verification and rollback runbook.

## Phase 6.1J — Relationship Manager and Sales Playbook

**Status:** Complete and deployed

Main outcomes:

- `relationship_manager` role;
- Business Development ownership on leads;
- private database-backed playbooks;
- dedicated Relationship Manager landing page;
- narrow CRM and next-action permissions;
- no pricing, approval, pipeline, deletion, or private-OS authority.

---

# 12. Current Official Roadmap

## Numbering decision

The roadmap is now numbered by execution priority, not by the date an idea was
first proposed.

```text
Phase 6 — Agency Operations and Production Safety
Phase 7 — Product Hardening and Growth
Phase 8 — Budget-Safe AI Continuation
Phase 9 — Affordable Ambient Assistant
```

Phase 6.1A–6.1J is complete. Production safety is now the first unfinished
agency requirement, so Backup and Disaster Recovery becomes Phase 6.2.

### Renumbering map

| Previous number | New number | Milestone |
|---|---:|---|
| Phase 7.1 | Phase 6.2 | Backup and Disaster Recovery |
| Phase 6.2 | Phase 6.3 | Lead Activity Timeline |
| Phase 7.9 | Phase 6.5 | Observability and Error Monitoring |
| Phase 6.4 | Phase 6.6 | Bulk Lead Management |
| Phase 7.4 | Phase 6.7 | Outreach Templates and Approval Controls |
| Phase 6.9 | Phase 6.8 | Lead-Sourcing Effort Tracking and Webhook Intake |
| Phase 6.5 | Phase 6.9 | Discovery and Qualification |
| Phase 6.6 | Active — 6.6A–6.6C implementation complete | Bulk preview, isolated Pendang CRM, and Pendang company knowledge; production acceptance and remaining bulk work next |
| Phase 6.7 | Phase 6.11 | Client Onboarding and Delivery |
| Phase 6.8 | Phase 6.12 | Retainers, Invoicing, and Profitability |
| Phase 6.10 | Phase 6.13 | Delegated Outreach Permission |
| Phase 7.2 | Phase 7.1 | Security and Audit Foundation |
| Phase 7.3 | Phase 7.2 | Notifications and Nudges |
| Phase 7.5 | Phase 7.3 | Insights and Trend Dashboard |
| Phase 7.6 | Phase 7.4 | Mobile-Friendly PWA |
| Phase 7.7 | Phase 7.5 | Data Export and Portability |
| Phase 7.8 | Phase 7.6 | Formal Staging Environment and Rollback |

The Phase 8 and Phase 9 numbering remains unchanged.

---

# Phase 6 — Agency Operations and Production Safety

**Status:** Active  
**Primary objective:** Protect the production system, capture every sales
interaction, and make the agency workflow reliable before adding optional AI.

## Phase 6.1 — Staff Collaboration, Approval, Relationship Management, and Playbooks

**Status:** Complete  
**Completed submilestones:** 6.1A–6.1J

Delivered:

- Lead Researcher ownership, editing, submission, and changes-requested flow;
- Owner research decisions, outreach approval, and pipeline gates;
- role-aware CRM queues;
- forged-request and direct-route protection;
- staging-copy verification and rollback documentation;
- Relationship Manager role and dedicated landing page;
- Business Development ownership;
- private database-backed sales playbooks;
- narrow next-action and CRM permissions;
- no XP changes from CRM staff workflows.

The attached Junmar operating rule remains authoritative:

> Junmar opens relationships. Mark diagnoses, prices, closes, and delivers.

## Phase 6.2 — Backup and Disaster Recovery

**Status:** Complete  
**MoSCoW:** Must have now

### Goal

Protect the Railway SQLite database and prove that MARK-OS can be restored
without guessing during an incident.

### Required deliverables

- safe SQLite online-backup command;
- timestamped backup files;
- `PRAGMA quick_check` and foreign-key verification;
- SHA-256 checksum and backup manifest;
- configurable retention and cleanup;
- restore-to-new-file command;
- automated restore verification;
- Railway persistent-volume backup procedure;
- scheduled backup execution;
- encrypted offsite copy outside the Railway volume;
- backup success and failure log;
- documented production recovery runbook.

### Protection layers

```text
Live Railway volume
+ verified local/staging copy
+ scheduled backup outside the live database file
+ encrypted offsite backup
+ periodic restore test
```

### Definition of done

- no backup command writes to or locks the live database incorrectly;
- every produced backup passes integrity and foreign-key checks;
- a backup can be restored into a new database file;
- a temporary MARK-OS instance starts successfully from the restored file;
- retention cannot delete the live database;
- scheduled backup failure is visible to Mark;
- the recovery runbook contains exact Railway and local commands;
- full test suite passes.

## Phase 6.3 — Lead Activity Timeline

**Status:** Complete
**MoSCoW:** Must have now

### Goal

Store every meaningful lead interaction instead of only the latest status and
next action.

### New table

Recommended table:

```text
lead_activities
```

Required fields:

```text
id
lead_id
activity_type
activity_at
channel
message_summary
notes
created_by_user_id
performed_by_user_id
responsible_user_id
response_status
next_follow_up_date
created_at
updated_at
deleted_at
corrected_by_user_id
correction_reason
```

Activities are append-first. Corrections must retain the original author and
an auditable correction reason.

### Initial activity types

```text
research_started
research_completed
submitted_for_review
changes_requested
approved_for_outreach
linkedin_message_sent
email_sent
follow_up_sent
reply_received
call_scheduled
meeting_completed
proposal_sent
client_decision
```

### Contact audit rule

Every contacted lead must record, atomically:

```text
date contacted
message channel
message summary
next follow-up date
responsible staff member
current response status
```

### Implementation progress

- [x] 6.3A — Additive activity schema, indexes, validation, and migration tests
- [x] 6.3B — Validated activity service and role permissions
- [x] 6.3C — Lead-detail timeline and correction forms
- [x] 6.3D — Atomic Contacted transition and phase verification

### Definition of done

- migration is additive and existing leads remain readable;
- timeline is displayed on lead detail in chronological order;
- activity author, performer, and responsible staff are preserved;
- corrections and soft deletions are auditable;
- an outreach-related Contacted transition cannot occur without its activity;
- Owner, Lead Researcher, and Relationship Manager permissions are tested;
- full test suite passes.

## Phase 6.4 — Follow-up Command Center

**Status:** Complete
**MoSCoW:** Must have now

### Goal

Provide an in-app operational queue so outreach does not depend on memory.

### Required views

```text
Due Today
Overdue
Due This Week
Waiting for Reply
No Contact for Five Days
Approved but Not Contacted
Research Awaiting Review
Changes Requested
Interested — Handoff to Mark
Proposal Follow-up Required
```

### Requirements

- deterministic counts and urgency sorting;
- filters by assignee, researcher, and Business Development Owner;
- Owner view across the CRM;
- Lead Researcher and Relationship Manager views limited to permitted leads;
- activity-based last-contact calculation;
- safe empty states;
- date-boundary and timezone tests;
- no external notification dependency.


### Implementation progress

- [x] 6.4A — Deterministic queue service, activity-derived dates, role
  scoping, filters, and Manila boundary tests
- [x] 6.4B — Command Center route, filters, queue cards, and safe empty states
- [x] 6.4C — Isolation, date-boundary, rendering, and phase-completion
  verification

## Phase 6.5 — Observability and Error Monitoring

**Status:** Complete
**MoSCoW:** Must have now

### Goal

Make production failures visible before a staff member or prospect reports
them.

### Required deliverables

- structured application-error logging distinct from access logs;
- request or correlation IDs;
- migration and startup failure logging;
- authentication and authorization failure summaries without sensitive data;
- backup failure visibility;
- uptime check against `/health`;
- Owner alert through one low-cost channel;
- minimal error count for the previous 24 hours;
- documented Railway log-review procedure.

This phase is intentionally lightweight. The goal is reliable awareness, not a
large monitoring platform.


### Implementation progress

- [x] 6.5A — Structured application errors, safe correlation IDs, startup
  failure events, and authentication/authorization summaries
- [x] 6.5B — Backup failure visibility, `/health` uptime check, and one
  low-cost Owner alert path
- [x] 6.5C — Previous-24-hour error count, Railway log-review runbook, and
  phase-completion verification

### Phase 6.5 production operations runbook

#### One-time Railway configuration

Set these Railway service variables without committing their real values:

```text
MARK_OS_HEALTH_URL=https://YOUR-SERVICE.up.railway.app/health
MARK_OS_HEALTH_TIMEOUT_SECONDS=10
MARK_OS_OWNER_ALERT_WEBHOOK_URL=YOUR_DISCORD_WEBHOOK_SECRET
MARK_OS_BACKUP_DIR=/app/data/backups
MARK_OS_BACKUP_PREFIX=mark_os
MARK_OS_BACKUP_MAX_AGE_HOURS=26
```

Keep the Discord webhook secret only in Railway Variables or the local untracked
`.env`. Never paste it into logs, issues, commits, or screenshots.

Run the combined application-health and verified-backup check manually:

```bash
python tools/check_operations.py --json
```

Use the same command in the scheduled Railway operations service or cron job.
A healthy run exits `0`. An uptime or backup failure exits `1` and attempts one
Owner alert when the webhook is configured.

#### Previous-24-hour application-error count

Link the Railway CLI to the production project and service, then use either the
direct pipeline:

```bash
railway logs --since 24h --json --filter "@level:error" \
  | python tools/summarize_errors.py --json
```

or retain a temporary review file outside the repository:

```bash
railway logs --since 24h --json --filter "@level:error" \
  > /tmp/mark-os-errors-24h.ndjson

python tools/summarize_errors.py \
  --input /tmp/mark-os-errors-24h.ndjson
```

The summary counts only `mark_os.application` errors inside the exact bounded
window. It reports event counts, unique correlation IDs, and a small allowlisted
sample. It does not repeat request bodies, webhook URLs, traceback details,
passwords, authorization data, or arbitrary log fields.

#### Investigate one reported request

Copy the browser response's `X-Request-ID`, then search the application logs:

```bash
railway logs --since 24h --json \
  --filter "@correlation_id:PASTE_REQUEST_ID"
```

Review edge-level server errors separately:

```bash
railway logs --http --since 24h --status 500..599 --json
```

In the Railway dashboard, use the deployment log panel for one deployment or
the environment Log Explorer for cross-deployment review. Filter structured
application events with `@level:error`, `@event:application_error`, or the
correlation ID. Use View in Context only after identifying the safe event.

#### Incident review order

1. Confirm `/health` returns HTTP `200` and database status `ok`.
2. Run `python tools/check_operations.py --json`.
3. Generate the bounded previous-24-hour error summary.
4. Search the affected correlation ID.
5. Review the latest deployment and startup events.
6. Verify the newest backup and restore evidence before any database action.
7. Follow the Phase 6.2 recovery runbook rather than editing the live SQLite
   file during an incident.

## Phase 6.6 — Bulk Lead Management and CRM Workspaces

**Status:** Implementation complete (6.6A–6.6F); production acceptance next
**MoSCoW:** Should have soon

### Goal

Allow staff to research and import many leads without unsafe blind writes, and
operate separate CRM workspaces inside one MARK-OS deployment.

Pendang Research & Analytics must be implemented as a **workspace inside
MARK-OS**. Do not create a separate PendangOS application.

### Bulk import workflow

```text
Upload CSV
→ parse safely
→ preview rows
→ show valid rows
→ show duplicate warnings
→ show invalid rows
→ select rows
→ assign researcher and/or Business Development Owner
→ import
```

### Required features

- import preview that does not write;
- row-level validation;
- duplicate warnings before write;
- organization-scoped duplicate detection;
- selective import;
- bulk researcher assignment;
- bulk Business Development Owner assignment;
- bulk submission for review;
- permission-scoped CSV and JSON export;
- approved-leads export;
- downloadable CRM backup;
- CRM workspaces with server-side organization isolation.

### Implementation progress

- [x] 6.6A — Bulk lead import preview, row validation, and duplicate warnings
      without database writes
- [x] 6.6B — Pendang CRM workspace foundation, staff authority, isolation,
      optimistic edits, and release rehearsal harness
- [x] 6.6C — Pendang Company Knowledge and Marketing workspace
- [x] 6.6D — Selective row import with permission-scoped assignment
- [x] 6.6E — Bulk submission, CSV/JSON export, and approved-leads export
- [x] 6.6F — Downloadable CRM backup and phase verification

### Phase 6.6B — Pendang CRM Workspace and Staff Launch

**Status:** Immediate next milestone  
**MoSCoW:** Should have soon

#### Goal

Launch Pendang Research & Analytics as an organization-scoped CRM workspace
inside MARK-OS, with the correct staff roles, queues, and server-side data
isolation from MARK Agency.

#### Required foundation

1. Add `organizations` and `organization_memberships`.

2. Seed these organizations idempotently:

   ```text
   mark-agency
   pendang
   ```

3. Add `organization_id` to leads.

4. Safely backfill every existing lead into `mark-agency`.

   The backfill must preserve:

   - lead IDs;
   - quest relationships;
   - ownership fields;
   - research fields;
   - timestamps;
   - soft-delete state;
   - existing CRM behavior.

5. Enforce organization/workspace access on the server side.

   Every relevant lead list, lead detail, queue, search, filter, mutation,
   import, and duplicate check must respect organization scope.

   Never depend only on hiding UI controls for isolation.

6. **Mark role model**

   - preserve Mark's existing global owner/admin authority;
   - `membership_role = workspace_admin` in MARK Agency;
   - `membership_role = workspace_admin` in Pendang;
   - Mark may switch between authorized workspaces.

7. **Pendang — Rey**

   Rey must **not** receive the global owner role.

   Use the least-privileged existing global role that allows CRM entry,
   preferably:

   ```text
   global role = relationship_manager
   Pendang membership_role = workspace_owner
   ```

   UI label:

   ```text
   Pendang Workspace Owner / Managing Director
   ```

   Rey is restricted to Pendang.

   Rey must **not** have access to:

   - MARK Agency private CRM data;
   - Mark's private/family information;
   - global user administration;
   - global system settings.

   Within Pendang, Rey may perform the Pendang owner actions defined by the
   roadmap, including permitted research/outreach approvals and major pipeline
   decisions.

8. **Pendang — Freddy**

   Freddy:

   ```text
   global role = lead_sourcer
   Pendang membership_role = crm_contributor
   ```

   UI label:

   ```text
   Pendang Lead Researcher
   ```

   Freddy is restricted to Pendang and should receive only the CRM/research
   capabilities required for that role.

9. Keep **Business Development Owner** as a separate lead field.

   Do not replace lead creator, researcher, assignee, or ownership/history
   fields with the Business Development Owner field.

10. Provide the minimal Pendang workspace-scoped CRM queues required for launch,
    including the applicable:

    ```text
    Pending Research
    Owner Review
    Contacted
    Follow-up
    ```

11. Duplicate detection must be organization-aware.

    A lead in MARK Agency must not incorrectly block the same business from
    being created in Pendang merely because the identity exists in another
    organization, unless this document explicitly defines a global duplicate
    rule.

12. Keep the existing stack:

    ```text
    FastAPI
    HTMX
    Bulma
    SQLite
    ```

    Do not migrate to Django, React, PostgreSQL, or another stack.

13. Preserve SQLite production safeguards:

    - WAL journal mode;
    - busy timeout on every database connection;
    - short write transactions;
    - optimistic edit protection where concurrent edits can occur;
    - exactly one Railway application instance while production uses SQLite.

#### Definition of done

- organizations and memberships exist with idempotent seed data for
  `mark-agency` and `pendang`;
- every existing lead is backfilled to `mark-agency` without ID or relationship
  loss;
- Mark can switch between authorized workspaces;
- Rey and Freddy are restricted to Pendang with the defined role model;
- MARK Agency CRM data is not visible to Pendang-only staff through routes,
  services, imports, or duplicate checks;
- Pendang workspace queues render with organization-scoped counts and records;
- duplicate detection is scoped to the active organization;
- relevant permission and isolation tests pass;
- full test suite passes.


### Phase 6.6C — Pendang Company Knowledge and Marketing

**Status:** Implementation complete — production acceptance required

Delivered inside the existing Pendang workspace:

- dedicated `/pendang` company home and Pendang-specific shell navigation;
- editable Founder Plan, About, and Company CV;
- organization-scoped services/pricing, historical projects, case studies,
  warm relationships, manual Content Studio drafts, meeting preparation, and
  shared company-document links;
- server-side active Pendang membership revalidation for every read/write;
- read access for Pendang CRM contributors;
- write authority only for global Owner / Pendang workspace-admin or
  workspace-owner authority;
- optimistic row-version protection for company profile and knowledge edits;
- additive/idempotent SQLite tables, indexes, and safe Pendang seed content;
- no AI publishing, external action, file-upload storage, or fabricated client
  history introduced by this phase;
- Pendang staff now land on `/pendang` after completing the required temporary
  password change.

Production acceptance still requires deploying the additive migration, checking
`/health`, and completing the real Rey/Freddy login and role smoke tests.

## Phase 6.7 — Outreach Templates and Approval Controls

**Status:** Planned  
**MoSCoW:** Should have soon

### Goal

Turn approved playbook wording into deterministic, reusable CRM templates.

### Initial templates

```text
Warm introduction
LinkedIn message
Email introduction
3–5 business-day follow-up
Meeting handoff
Common-objection response
```

### Rules

- templates use explicit variables and safe previews;
- Mark controls approval and availability;
- Relationship Manager may prepare or copy only approved text;
- no automatic external sending;
- template usage is logged through Phase 6.3 activities;
- pricing, scope, deadline, and technical promises remain Owner-only.

## Phase 6.8 — Lead-Sourcing Effort Tracking and Webhook Intake

**Status:** Planned after Phase 6.6 is stable  
**MoSCoW:** Should have soon

### Effort tracking

Track:

```text
research_minutes
leads_researched
leads_submitted
changes_requested_count
approval_rate
relationship_actions
period_start
period_end
```

This is operational measurement, not payroll authority.

### Webhook intake

Add a narrow authenticated endpoint for external lead sources:

```text
POST /api/leads/intake
```

Requirements:

- per-source revocable token;
- payload validation;
- duplicate protection;
- same ownership, review, and approval rules as manual leads;
- no AI dependency;
- invalid and expired token tests.

## Phase 6.9 — Discovery and Qualification

**Status:** Trigger-based  
**Start condition:** Prospects reply or discovery meetings begin.

Required data:

```text
business_problem
business_impact
current_process
current_tools
estimated_hours_wasted
urgency
budget_range
decision_maker
desired_result
meeting_notes
recommended_service
qualification_status
```

Framework:

```text
Problem → Business Impact → Authority → Budget → Timing → Fit
```

Mark controls the final technical-fit and qualification decision.

## Phase 6.10 — Proposal Management

**Status:** Trigger-based  
**Start condition:** A qualified opportunity needs a proposal.

Required data:

```text
service_offered
engagement_type
proposed_price
expected_monthly_value
proposal_sent_at
proposal_url
proposal_expires_at
probability
follow_up_date
decision_status
decision_reason
```

First version uses a proposal link rather than a full document generator.
Mark retains pricing and proposal authority.

## Phase 6.11 — Client Onboarding and Delivery

**Status:** Trigger-based  
**Start condition:** Client #1 is won.

Agency loop:

```text
Lead
→ Conversation
→ Qualification
→ Proposal
→ Won
→ Onboarding
→ Delivery
→ Invoice
→ Payment
→ Renewal
→ Referral
```

Add client profiles, contacts, contract links, success criteria, deliverables,
tasks, approvals, change requests, and completion evidence.

## Phase 6.12 — Retainers, Invoicing, and Profitability

**Status:** Trigger-based  
**Start condition:** Active delivery and billing begin.

Add:

- recurring service periods;
- renewal and cancellation dates;
- invoice and payment status;
- collected revenue;
- pass-through expenses;
- contractor/staff delivery cost;
- gross profit and margin;
- commission calculation based on collected revenue.

Financial data remains Owner-only.

## Phase 6.13 — Delegated Outreach Permission

**Status:** Trigger-based  
**Start condition:** Phase 6.3 is complete and Mark approves a trusted
Relationship Manager after successful real-world use.

### Permission

```text
users.can_contact_leads
```

Default:

```text
false
```

### Rules

- granted and revoked per user by Owner only;
- intended primarily for `relationship_manager`;
- research must already be approved;
- outreach must already be approved;
- contact and activity creation occur atomically;
- action records channel, message summary, follow-up, responsible user, and
  response state;
- revocation takes effect immediately;
- no pricing, proposal, Won/Lost, reassignment, deletion, finance, or private-OS
  authority;
- direct and forged requests are tested.

---

# Phase 7 — Product Hardening and Growth

**Status:** Planned after the must-have Phase 6 safety and operations work

## Phase 7.1 — Security and Audit Foundation

Planned:

- login rate limiting;
- session inventory and logout everywhere;
- session revocation;
- admin-action and role-change audit;
- account activation/deactivation audit;
- failed-login events;
- CSRF and secure-cookie review;
- sensitive-log review;
- IDOR regression tests.

## Phase 7.2 — Notifications and Nudges

External delivery may include email, Telegram, or Discord.

Initial notifications:

- backup failure;
- app health failure;
- check-in reminder;
- overdue quest;
- lead next action due;
- weekly review reminder.

The in-app follow-up command center remains Phase 6.4.

## Phase 7.3 — Insights and Trend Dashboard

Use Chart.js first.

Include personal, CRM, Relationship Manager, conversion, source, pipeline,
activity, and recommendation-outcome trends.

## Phase 7.4 — Mobile-Friendly PWA

Add a manifest, icons, standalone installation, safe service worker, offline
shell, offline check-in draft, retry behavior, and mobile interaction
improvements.

Do not broadly cache authenticated personal HTML.

## Phase 7.5 — Data Export and Portability

Formats:

```text
JSON
CSV per table
ZIP package
```

Every export is user- and permission-scoped. Never export password hashes,
session secrets, API keys, or environment secrets.

## Phase 7.6 — Formal Staging Environment and Rollback

The staging-copy verifier and rollback runbook created during Phase 6.1 are the
foundation, not the final deployed staging environment.

Planned:

- low-cost staging service or repeatable copied-snapshot environment;
- pre-deploy migration rehearsal;
- exact application rollback steps;
- exact database restore steps;
- release evidence retained per deployment;
- scheduled restore drills.

---

# Phase 8 — Budget-Safe AI Continuation

**Status:** Planned after Phase 7 or when a business-critical AI use case justifies it  
**Previous numbering:** Phase 5.3 onward

The old Phase 5.3+ documents are preserved here under the new chronological
numbering.

## 8.1 Core AI rules

1. SQLite remains the source of truth.
2. The default is not to remember.
3. Never send the full database to an AI provider.
4. Use deterministic routing before model classification.
5. Use no model when Python can complete the request.
6. Model suggestions are not database writes.
7. Important writes require confirmation.
8. Every run is audited.
9. Retrieval is scoped to the authenticated user.
10. The app works when AI is disabled.

## 8.2 High-level request flow

```text
Authenticated request
→ authorization and validation
→ save message with idempotency key
→ create agent audit
→ deterministic intent checks
→ no-model path or selected AI loop
→ scoped context builder
→ token and budget gate
→ provider call
→ structured output validation
→ proposed actions
→ confirmation when required
→ service execution
→ save response
→ complete audit
→ optional memory candidate
```

## 8.3 Eight controlled agent loops

```text
direct_answer
director_coach
quest_planning
client_hunting
review_reflection
memory_management
data_lookup
tool_action
```

These are controlled loops or workflow nodes, not eight unrestricted agents.

Start with one Director workflow.

## 8.4 Intent routing

Deterministic examples:

```text
"remember ..."              → memory_management
"forget ..."                → memory_management
"show my memories"          → memory_management
"what should I do next?"    → director_coach
"create a quest ..."        → quest_planning
"review this lead ..."      → client_hunting
"what is my level?"         → data_lookup
"send an email ..."         → tool_action
```

Only use an AI intent classifier when deterministic checks are inconclusive.

## 8.5 Provider architecture

Use a provider-independent gateway.

Suggested capabilities:

```text
none
routine
deep
embedding
```

Suggested adapters only when needed:

```text
DisabledProvider
OpenAIProvider
OllamaProvider
OpenAI-compatible provider
```

Model names and endpoints must come from environment variables.

Do not assume that a laptop-local Ollama endpoint is reachable by Railway.

## 8.6 Structured AI output

The model should return an application contract, not unrestricted instructions.

The application must reject:

- unknown action types;
- malformed or extra arguments;
- raw SQL;
- cross-user IDs;
- secret values;
- unsupported memory scope;
- actions that bypass confirmation.

## 8.7 Memory layers

### Operational records

Do not copy complete operational records into memory merely for retrieval.

### Raw chat

```text
chat_sessions
chat_messages
```

### Chat summaries

Planned compressed older conversation windows.

### Structured memory

Store durable:

- preferences;
- constraints;
- decisions;
- lessons;
- patterns;
- outcomes;
- explicitly requested memories.

Do not automatically store:

- greetings;
- acknowledgements;
- every short reply;
- temporary errors;
- repeated text;
- raw full conversations;
- credentials;
- banking information;
- unnecessary confidential work information.

### Memory candidates and audit

Extraction should produce candidates before durable storage when confidence or
sensitivity requires review.

Memory changes should be auditable.

## 8.8 Retrieval

### First retrieval version

Use deterministic SQLite filtering and ranking first.

No embeddings are required for the first useful version.

### Optional semantic retrieval

Initial vector option:

```text
SQLite + sqlite-vec
```

Future production option:

```text
PostgreSQL + pgvector
```

Embedding model is environment-configured.

A dimension near 768 may be used when supported, but must not be hardcoded
without provider verification.

Embed:

- summarized durable memories;
- completed quest outcomes;
- important decisions;
- useful technical solutions;
- weekly summaries.

Do not embed every chat message.

## 8.9 Context packet

Default AI context should contain only what is needed:

1. system identity and safety rules;
2. authenticated user context;
3. profile summary;
4. current level and XP;
5. latest check-in;
6. limited active goals/projects/quests;
7. selected CRM record when relevant;
8. a small set of relevant memories;
9. up to ten recent messages;
10. the new user message.

"Up to ten" is a maximum, not a minimum.

## 8.10 Budget controls

Target:

```text
PHP 200 per month
```

Required controls:

- hard maximum input;
- hard maximum output;
- daily request cap;
- daily spend cap;
- monthly spend cap;
- at most one controlled fallback;
- no unlimited retry loop;
- usage record for every response;
- cheap model path first;
- strong model only for justified high-value work;
- database-only features continue at the hard budget limit.

## 8.11 Tool permissions

### Read automatically when authorized

- own profile;
- own goals;
- own projects;
- own quests;
- own check-ins;
- own memories;
- authorized CRM records;
- approved activity history.

### Prepare without executing

- proposed quest;
- proposed outreach;
- proposed lead status;
- proposed memory;
- proposed review.

### Require confirmation

- complete a quest;
- award manual XP;
- send external communication;
- delete data;
- change an important goal;
- change major CRM stage;
- change price;
- mark Won/Lost;
- spend money;
- write external calendar/email data.

### Prohibited

- unrestricted SQL;
- secrets extraction;
- cross-user retrieval;
- bypassing role permissions;
- hidden external actions;
- unlimited autonomous loops.

## 8.12 Future AI implementation sequence

Suggested sequence after Phase 7:

```text
Phase 8.1  Structured-memory schema completion
Phase 8.2  Manual Memory Center
Phase 8.3  Retrieval and Context Builder
Phase 8.4  Intent Router and AI Gateway
Phase 8.5  Routine AI Chat
Phase 8.6  Memory Extraction
Phase 8.7  Confirmed Tool Actions
Phase 8.8  Optional Semantic Retrieval
Phase 8.9  Optional Neo4j relationship memory
Phase 8.10 Optional LangGraph Director workflow
Phase 8.11 Weekly Review Loop
Phase 8.12 Approved external observation integrations
```

The M8–M10 ownership work means the old Phase 5.3 ownership requirement is
already substantially complete. Phase 8 should not repeat that migration.

---


# Phase 9 — Affordable Ambient Assistant

**Status:** Planned  
**Previous proposal name:** Ambient Assistant  
**Primary objective:** Make MARK-OS feel present, conversational, and proactive
without increasing the existing PHP 200 monthly AI budget.

## Preconditions

The complete Phase 9 experience should begin only after these Phase 8
foundations are stable:

```text
Phase 8.4  Intent Router and AI Gateway
Phase 8.7  Confirmed Tool Actions
```

Phase 8.4 is required so every model request passes through one budget-aware
router.

Phase 8.7 is required before MARK-OS can perform consequential actions from a
voice command or an external channel.

The browser-only voice controls and deterministic nudge rules may be prototyped
earlier, but they must not bypass Phase 8 permissions or spending controls.

## Phase 9 affordability policy

Phase 9 must not create a second AI budget.

```text
Total MARK-OS AI budget: PHP 200 per month
Preferred Phase 9 incremental AI spend: PHP 0–30 per month
Normal voice and nudge operation: PHP 0 in model charges
```

The PHP 0–30 allowance is part of, not additional to, the PHP 200 total limit.

### Cost rules

1. Use browser and operating-system speech features before paid speech APIs.
2. Use deterministic rules for reminders and context selection.
3. Do not call a model merely to decide whether a reminder is due.
4. Do not generate an AI draft until the user explicitly requests it.
5. Reuse deterministic outreach templates before asking AI to write.
6. Cache prepared context instead of repeatedly summarizing the same records.
7. Prefer Telegram or Discord before SMS.
8. Keep SMS deferred because it introduces per-message charges.
9. Do not run continuous cloud transcription.
10. Do not send background prompts merely to make the assistant appear active.
11. Count every Phase 9 model call through the existing Phase 8 audit and
    monthly budget gate.
12. When the budget is exhausted, voice capture, deterministic nudges, and
    local navigation must continue working.

---

## Phase 9.1 — Browser Voice Input and Output

**Priority:** High  
**Expected additional model cost:** None

### Goal

Allow Mark to speak check-ins and chat messages and hear selected responses
without adding a paid speech provider.

### First implementation

Use browser-supported speech capabilities for:

- speech-to-text input for chat;
- speech-to-text input for daily check-ins;
- text-to-speech for selected responses;
- push-to-talk controls;
- stop-speaking control;
- editable transcription before submission.

### Affordability design

- use browser APIs and device capabilities;
- do not upload continuous microphone audio to MARK-OS;
- do not add a paid speech-to-text service in the first version;
- submit only the final text through the existing chat route;
- text-to-speech reads an already generated response and does not trigger
  another model call;
- provide typed-input fallback when speech is unavailable.

### Privacy and safety

- microphone access requires explicit browser permission;
- listening begins only after a visible user action;
- display a clear listening indicator;
- do not store raw audio;
- do not auto-submit uncertain transcriptions;
- consequential actions still require confirmation.

### Definition of done

- Mark can dictate a check-in;
- Mark can review and edit the transcript before saving;
- MARK-OS can read a response aloud;
- voice controls work without changing the chat service contract;
- no raw audio is stored;
- typed operation remains fully available.

---

## Phase 9.2 — Proactive Check-ins and Deterministic Nudges

**Priority:** Highest  
**Expected additional model cost:** None by default

### Goal

Allow MARK-OS to speak first through useful, rule-based reminders.

### Initial deterministic triggers

```text
No energy check-in by the configured evening time
Quest overdue
Quest due today
Lead has had no contact for four or five days
Follow-up due today
Research waiting for Owner review
Approved lead not yet contacted
Weekly review not completed
```

### Example messages

```text
You have not logged your energy today. Start a quick check-in?

Lead X has had no contact for five days. Open the lead?

Research for Lead Y is waiting for your review.
```

These messages are rendered from templates and do not require AI.

### AI use

A nudge may offer an optional action such as:

```text
Draft follow-up
Summarize lead
Suggest next action
```

The model is called only after the user selects the action.

### Affordability controls

- one active nudge per resource and rule;
- daily deduplication;
- quiet hours;
- per-user notification preferences;
- snooze and dismiss actions;
- maximum daily nudge count;
- no model call for trigger evaluation;
- use cached lead context for an optional draft;
- use deterministic outreach templates before AI drafting.

### Delivery order

Start with:

```text
1. In-app notification center
2. Browser notification when the app is installed or open
3. External channels in Phase 9.4
```

### Definition of done

- MARK-OS produces useful nudges without AI;
- duplicates are prevented;
- quiet hours are respected;
- Mark can open the relevant record directly;
- optional AI actions pass through the Phase 8 budget router;
- the application remains useful at the hard monthly AI limit.

---

## Phase 9.3 — Optional Local Wake Word

**Priority:** Stretch  
**Expected additional model cost:** None  
**Default status:** Disabled

### Goal

Allow a personally controlled device to open a MARK-OS voice session after a
wake phrase.

### First-version boundaries

- local-only wake-word detection;
- opt-in per device;
- no always-listening cloud service;
- wake word opens a visible voice session;
- the user still confirms consequential actions;
- raw audio is not stored by MARK-OS.

A lightweight offline detector such as `openWakeWord` may be evaluated, but
the implementation must remain optional.

### Why this is later

- continuous microphone use affects privacy and battery life;
- mobile browser support may be limited;
- background execution is more complex than push-to-talk;
- it adds little business value compared with Phase 9.1 and Phase 9.2.

### Affordability design

- run detection locally;
- use a small offline model;
- do not transcribe until the wake word is detected;
- do not keep a server connection open only for listening;
- do not introduce a paid voice provider.

### Definition of done

- wake-word mode is explicitly enabled by the user;
- it can be disabled immediately;
- detection stays local;
- a visible session opens after detection;
- typed and push-to-talk modes remain the default reliable options.

---

## Phase 9.4 — Low-Cost Multi-Channel Presence

**Priority:** Medium  
**Expected additional model cost:** Controlled by Phase 8  
**Preferred channels:** Telegram first, Discord second

### Goal

Allow the same authenticated Director and loop router to respond through a
small number of low-cost channels.

### Channel order

```text
1. Telegram bot
2. Discord direct message or private channel
3. Email notification links
4. SMS only when financially justified
```

SMS is not part of the affordable first release because it adds a direct
per-message cost.

### Architecture

```text
Incoming channel message
→ verify channel identity
→ map channel user to MARK-OS user
→ apply role and resource permissions
→ route through Phase 8 intent and budget controls
→ create proposed action
→ request confirmation when required
→ save audit trail
→ return a concise response
```

### Cost controls

- no unsolicited AI conversation loops;
- concise default responses;
- deterministic commands for data lookup;
- channel-specific daily message caps;
- one model call per accepted user request where possible;
- no automatic retry storm;
- no full-chat history sent on every message;
- use small scoped context packets;
- external channels may display a link to complete complex work in the web app.

### Security requirements

- channel identity linking requires an authenticated one-time process;
- channel tokens remain in environment secrets;
- family and staff roles keep the same permissions as the web app;
- external channels cannot bypass confirmation;
- lost-device/channel revocation is available;
- all actions are auditable.

### Definition of done

- one low-cost external channel works;
- channel identity is linked safely;
- permissions match the web app;
- messages use the Phase 8 router and budget gate;
- SMS is still disabled unless Mark explicitly approves the expense.

---

## Phase 9.5 — Careful Ambient Context Awareness

**Priority:** Last  
**Privacy risk:** High  
**Expected additional model cost:** Low only when event-driven

### Goal

Prepare relevant context at the right moment without continuously reading or
summarizing private accounts.

### Initial examples

```text
A meeting with Client X starts in 20 minutes.
Open the last three CRM activities?

A follow-up deadline is today.
Open the lead and deterministic template?

A calendar event matches an approved CRM client.
Show the linked notes?
```

### First integrations

- Google Calendar read-only observation;
- Gmail metadata or specifically approved messages only;
- authorized CRM records;
- local MARK-OS tasks and follow-up dates.

### Affordability design

- use event or schedule triggers instead of frequent polling;
- retrieve only the needed event or message metadata;
- do not summarize the entire inbox;
- do not call AI merely to check whether a meeting exists;
- use stored CRM summaries before generating a new summary;
- generate meeting preparation only after Mark opens or requests it;
- cap context preparation length;
- cache the prepared briefing for the event.

### Privacy rules

- use the minimum OAuth scopes;
- read-only first;
- do not ingest unrelated email;
- do not store credentials in the database;
- record which source supplied each context item;
- external writes require explicit confirmation;
- provide disconnect and data-removal controls.

### Definition of done

- one read-only context source is connected;
- MARK-OS presents a useful deterministic heads-up;
- AI preparation is optional;
- unrelated private data is excluded;
- disconnecting the source stops future access.

---

## Phase 9.6 — Personality and Response Shaping

**Priority:** Medium  
**Expected additional model cost:** None by itself

### Goal

Make every MARK-OS interaction feel consistent whether it comes from a
template, the Director, chat, a reminder, or an external channel.

### Configuration

Store a small user-controlled response profile, such as:

```text
tone
response_length
directness
encouragement_level
use_of_humor
voice_output_enabled
preferred_name
quiet_hours
```

Example tone choices:

```text
Direct and concise
Warm coach
Professional operator
Calm strategic advisor
```

### Affordability design

- deterministic messages use local templates;
- personality settings are added to model context only when a model is already
  being called;
- do not call AI solely to rewrite a notification into the selected tone;
- use short reusable phrasing libraries;
- keep voice selection on the device/browser when possible.

### Safety rule

Personality changes presentation, not permissions, facts, risk controls, or
confirmation requirements.

### Definition of done

- Mark can select a consistent tone;
- deterministic and AI responses follow the same general style;
- the setting does not create additional AI calls;
- safety and permission messages remain clear.

---

## Phase 9 Build Order

```text
Phase 9.1  Browser Voice Input and Output
Phase 9.2  Proactive Check-ins and Deterministic Nudges
Phase 9.6  Personality and Response Shaping
Phase 9.4  Telegram or Discord Presence
Phase 9.5  Careful Ambient Context Awareness
Phase 9.3  Optional Local Wake Word
```

The wake-word feature is intentionally last because it has the weakest
business return and the greatest device/privacy complexity.

## Phase 9 Definition of Done

Phase 9 is complete when:

- browser voice input works without a paid speech provider;
- selected responses can be read aloud;
- proactive nudges are deterministic and deduplicated;
- optional AI actions use the Phase 8 router and budget gate;
- the total AI cap remains PHP 200 per month;
- one low-cost external channel works securely;
- personality settings do not trigger extra model calls;
- ambient context is read-only, minimal, and event-driven;
- wake-word mode remains optional and local;
- the app stays useful when AI spending is disabled.

---

# 13. Development and Migration Rules

## 13.1 Database migration order

For old SQLite databases:

```text
create base tables
→ inspect columns
→ add missing columns
→ backfill values
→ rebuild tables only when necessary
→ create dependent indexes
→ validate schema
→ validate foreign keys
→ install ownership triggers
```

Never create an index for a new column before the column migration.

Never use a non-constant SQLite default in an incompatible `ALTER TABLE`.

Every migration must be safe to run more than once.

## 13.2 Ownership and authorization

- enforce restrictions in Python services and routes;
- hiding a button is not authorization;
- cross-user IDs must return `404` or a safe denial;
- do not trust form-supplied user IDs;
- infer the acting user from the authenticated session;
- audit consequential administrative changes.

## 13.3 Git workflow

For every milestone:

```bash
git switch main
git pull --ff-only origin main
git status
git switch -c feature/<milestone-name>
```

Then:

1. back up the database before schema changes;
2. implement one milestone;
3. run targeted tests;
4. run the full test suite;
5. perform a browser smoke test;
6. review `git diff`;
7. stage only intended files;
8. commit;
9. push the feature branch;
10. merge only after tests pass;
11. deploy explicitly;
12. update this file.

Do not commit:

```text
.env
SQLite database files
backup files
.mark_os_backups/
temporary fix scripts
__pycache__/
local secrets
```

## 13.4 Testing

Tests must use temporary SQLite databases.

Tests must never target:

```text
data/mark_os.db
the Railway production volume
```

Run:

```bash
python -m pytest -q
```

GitHub Actions should run the same full suite on pushes and pull requests.

## 13.5 Release safety

Before Railway deployment:

1. review and commit all changes;
2. back up the persistent database;
3. confirm environment variables;
4. confirm the volume mount and database path;
5. deploy intentionally;
6. verify `/health`;
7. log in as Owner;
8. verify role-specific navigation;
9. test one non-destructive CRM operation;
10. verify the linked quest and dashboard;
11. review production logs.

---

# 14. Local Setup

## macOS or Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set at minimum:

```text
MARK_OS_USERNAME
MARK_OS_PASSWORD
SESSION_SECRET
```

Optional local database path:

```text
MARK_OS_DB_PATH=data/mark_os.db
```

Run:

```bash
uvicorn --env-file .env app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
http://127.0.0.1:8000/crm
http://127.0.0.1:8000/health
```

## Windows PowerShell

Create and activate:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Run through:

```powershell
uvicorn --env-file .env app.main:app --reload
```

or use the existing `run.ps1` helper.

---

# 15. Current Immediate Work

Begin:

```text
Phase 6.3 — Lead Activity Timeline
```

Recommended branch:

```bash
cd /Users/johnionmiranda/Documents/projects/mark-os

git switch main
git pull --ff-only origin main
git status

git switch -c feature/phase-6-3-lead-activity-timeline
```

Before coding, inspect:

```text
app/database.py
app/db/migrations.py
app/main.py
railway.json
requirements.txt
tools/verify_phase_6_1_release.py
tools/verify_phase_6_1j_release.py
PHASE_6_1_HI_RELEASE_RUNBOOK.md
tests/test_application.py
tests/test_crm_migrations.py
tests/test_relationship_manager.py
```

### Phase 6.2 implementation order

```text
6.2A  Online SQLite backup service and explicit CLI
6.2B  Integrity checks, checksum, and manifest
6.2C  Retention rules with live-database protection
6.2D  Restore-to-new-file command and restore verifier
6.2E  Railway volume procedure and scheduled execution
6.2F  Encrypted offsite copy and failure visibility
6.2G  Tests, browser/CLI smoke test, and recovery runbook
```

Do not begin Phase 6.3 until one complete restore test succeeds from a produced
backup.

---

# 16. MoSCoW Priorities

## Must have now

### Phase 6.2 — Backup and Disaster Recovery

- safe online SQLite backup;
- scheduled production backup;
- integrity and foreign-key checks;
- checksum and manifest;
- retention without live-file risk;
- offsite encrypted copy;
- tested restore;
- exact recovery runbook;
- backup failure visibility.

### Phase 6.3 — Lead Activity Timeline

- append-first activity history;
- date, channel, message summary, next follow-up, responsible staff, and
  response status for every contact;
- activity author and performer;
- correction audit;
- atomic Contacted transition and activity creation.

### Phase 6.4 — Follow-up Command Center

- Due Today, Overdue, Due This Week, Waiting for Reply, and stale-lead queues;
- Owner, Lead Researcher, and Relationship Manager scoped views;
- activity-based last-contact calculation;
- deterministic date tests.

### Phase 6.5 — Observability and Error Monitoring

- `/health` uptime monitoring;
- structured application errors;
- migration, authentication, and backup failure visibility;
- low-cost Owner alert;
- Railway log-review instructions.

## Should have soon

- Phase 6.6B Pendang CRM workspace and staff launch;
- Phase 6.6 bulk selective import, assignment, export, and backup (6.6D onward);
- Phase 6.7 deterministic approved outreach templates;
- Phase 6.8 effort tracking and authenticated webhook intake;
- Phase 7.1 security and audit hardening after the immediate operational risks;
- Phase 7.2 external notification delivery using the observability channel.

## Could have later or when triggered

- Phase 6.9 discovery and qualification after replies or meetings;
- Phase 6.10 proposal management when a proposal is needed;
- Phase 6.11 onboarding and delivery after Client #1;
- Phase 6.12 invoicing, retainers, profitability, and commission after billing;
- Phase 6.13 delegated outreach after the activity timeline and successful
  Relationship Manager pilot;
- Phase 7.3 insights dashboard;
- Phase 7.4 PWA;
- Phase 7.5 full data portability;
- Phase 7.6 formal deployed staging;
- Phase 8 budget-safe AI;
- Phase 9 ambient assistant;
- embeddings, Neo4j, LangGraph, Gmail, and Calendar observation only when a
  proven use case justifies them.

## Will not have yet

- unrestricted autonomous agents;
- automatic external outreach;
- Relationship Manager pricing, proposal, Won/Lost, or payment authority;
- full proposal document generation before the proposal workflow is needed;
- complex invoicing before Client #1 and active billing;
- AI as the database;
- AI-generated raw SQL;
- embedding every chat message;
- automatic storage of every conversation as memory;
- unconfirmed external actions.

---

# 17. Safety Rules

1. Database records are the source of truth.
2. AI never receives unrestricted database access.
3. Role restrictions are enforced server-side.
4. Family data is private by default.
5. Lead Researchers and Relationship Managers cannot access private finance.
6. Staff cannot approve outreach, set pricing, create proposals, or mark Won/Lost.
7. Major status, pricing, scope, and delivery decisions belong to Mark.
8. Ordinary deletion is soft deletion.
9. Permanent purge is not a normal UI action.
10. Quest XP is immutable and awarded once.
11. Secrets are never stored in memory or exports.
12. External actions require confirmation.
13. Migrations preserve existing production data.
14. Verified backups and restore evidence are required before risky deployment and schema changes.
15. The system must fail safely when optional services are unavailable.

---

# 18. Phase Completion Log

| Phase | Status | Notes |
|---|---|---|
| Phases 1–3 | Complete | Core application and deployment foundation |
| Phase 4 | Complete | Revised Quest Engine |
| Phase 5.1 | Complete | Persistent chat |
| Phase 5.2 | Complete | Agent audit |
| M1–M10 | Complete | Multi-user, family isolation, workspace release |
| Phase 6.1A–6.1I | Complete | Staff research, review, approval, queues, security, and release verification |
| Phase 6.1J | Complete and deployed | Relationship Manager, private playbook, and Business Development ownership |
| Phase 6.2 | Complete | Backup and Disaster Recovery |
| Phase 6.3 | Complete | Lead Activity Timeline, auditable corrections, and atomic Contacted transition |
| Phase 6.4 | Complete | Follow-up Command Center, role-scoped filters, Manila boundaries, and safe empty states |
| Phase 6.5 | Complete | Structured errors, correlation IDs, database-aware health, backup and uptime alerts, 24-hour count, and Railway runbook |
| Phase 6.6 | Implementation complete (6.6A–6.6F); production acceptance next | Bulk lead preview, Pendang CRM workspace, Pendang company knowledge, selective import, bulk submission/export, downloadable backup |
| Phase 6.7 | Complete | Outreach Templates and Approval Controls |
| Phase 6.8 | Should soon | Lead-sourcing effort tracking and webhook intake |
| Phase 6.9 | Trigger-based | Discovery and Qualification |
| Phase 6.10 | Trigger-based | Proposal Management |
| Phase 6.11 | Trigger-based | Client Onboarding and Delivery |
| Phase 6.12 | Trigger-based | Retainers, Invoicing, and Profitability |
| Phase 6.13 | Trigger-based | Delegated Relationship Manager outreach |
| Phase 7 | Planned | Product Hardening and Growth |
| Phase 8 | Planned | Budget-Safe AI Continuation |
| Phase 9 | Planned | Affordable Ambient Assistant |

---

# 19. Decision Log

Entries are kept in full for roughly the current and prior phase substep, since
that is the period an active contributor needs to reason about. Older entries
that a later decision explicitly supersedes are condensed to one line; see the
git history for full original text if needed.

## 2026-08-08 — Make Pendang company knowledge a workspace-owned surface

**Decision:**

- make `/pendang` the company home for authenticated users whose active business
  workspace is Pendang;
- keep MARK-OS as the underlying application, security boundary, and source of
  operational truth;
- store Founder Plan, About / Company CV, services, historical projects, case
  studies, warm relationships, content drafts, meeting preparation, and document
  references under the Pendang organization rather than as global records;
- allow Pendang CRM contributors to read verified company knowledge while
  reserving writes for Owner/workspace-owner or workspace-admin authority;
- revalidate membership in the database for company-content operations and use
  optimistic row versions for concurrent edits;
- keep Content Studio manual in this phase and do not trigger AI generation,
  publishing, outreach, or other external actions;
- store document references/links only in this phase rather than introducing a
  new file-upload subsystem;
- do not seed invented prices, clients, historical projects, case studies, or
  relationships.

**Reason:**

- Rey and Freddy need one shared company context immediately after onboarding;
- company knowledge must follow the same organization isolation model as CRM
  data instead of becoming a second Pendang application;
- verified content can grow incrementally without weakening production safety or
  creating another framework/runtime to maintain.

## 2026-08-08 — Pull forward a read-only Pendang Founder Plan surface

**Decision:**

- add the already-drafted Pendang Founder Plan as a read-only onboarding and
  alignment surface inside the Pendang CRM;
- keep the editable/database-backed Founder Plan and the broader About,
  Services, projects, case studies, documents, and Content Studio work in the
  remaining Phase 6.6C scope;
- show the Founder Plan only when the authenticated active workspace is
  `pendang`;
- use the established founder direction:
  - Rey — Managing Director / Chief Statistical Officer;
  - Mark — Co-Founder / Chief Technology & Data Officer;
  - Freddy — Senior Statistical Consultant / Lead Researcher;
  - focus on research/statistics, data/BI, data engineering/automation, and
    practical AI;
  - target researchers/universities, healthcare, NGOs, and SMEs;
  - keep one operating history in MARK-OS;
  - first objective: Leads → Clients → Projects → Payment → Referrals;
- replace the visible `MARK OS Fieldbook` identity with Pendang-specific
  branding while the active business workspace is Pendang;
- retain MARK-OS as the underlying application and security boundary.

**Reason:**

- Rey and Freddy can see the company direction immediately after completing
  their temporary-password change;
- displaying existing founder guidance does not require a new company-content
  database or weaken CRM workspace isolation;
- Pendang should feel like its own business workspace rather than a MARK Agency
  page with a different dataset.


## 2026-08-07 — Require production-copy rehearsal before Pendang onboarding

**Decision:**

- split final Phase 6.6B acceptance into a code/harness gate and a real
  production-copy rehearsal gate;
- never mark migration rehearsal complete merely because temporary pytest
  databases pass;
- use the existing SQLite online-backup API to capture a source safely,
  including WAL-backed databases;
- restore to a new file and run current migrations only on that restored copy;
- compare existing lead business fields, IDs, quest links, activity links, and
  protected row counts before and after migration;
- verify workspace schema, row versions, scoped dedupe protection, revocable
  memberships, WAL, busy timeout, integrity, foreign keys, and `/health`;
- keep Railway replica count, production volume/path confirmation, controlled
  deploy window, actual staff onboarding, real Pendang leads, and post-deploy
  health as explicit manual gates;
- store rehearsal artifacts in a Git-ignored local evidence directory.

**Reason:**

- Phase 6.6B changes production schema, authorization, routing, and concurrency
  behavior at the same time;
- synthetic test databases cannot prove that the real production dataset will
  migrate without unexpected legacy state;
- SQLite WAL databases must be backed up through a verified online-backup path,
  not by copying only the main database file;
- explicit unchecked manual gates prevent documentation from claiming a
  production launch that has not actually happened.

## 2026-08-07 — Reject stale CRM lead writes with an explicit row version

**Decision:**

- add `row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version >= 1)` to the
  lead record;
- increment the version on every application write that changes mutable lead
  state or active lead ownership;
- render the current version into every mutable lead form;
- require runtime writes to match lead ID + active organization ID + expected
  row version;
- return a specific stale-edit message instead of treating a concurrent change
  as a generic validation failure;
- keep the Contacted activity and pipeline transition inside the existing
  atomic savepoint so a stale pipeline write cannot leave an orphan contact
  activity;
- let administrative reassignment/revocation advance the version even though
  those operations are authoritative rather than browser edits;
- keep append-first `lead_activities` audit records on their own correction
  model rather than coupling them to the lead version.

**Reason:**

- Mark, Rey, and Freddy may open the same Pendang record at different times;
- SQLite serializes writes but does not by itself prevent a later stale form
  from overwriting a newer committed value;
- organization scoping prevents cross-workspace access, while `row_version`
  separately prevents lost updates inside the same workspace;
- an additive integer token is deterministic, cheap, SQLite-friendly, and easy
  to test without introducing another framework or database.

## 2026-08-07 — Make workspace identity visible and temporary credentials one-time

**Decision:**

- expose business workspace switching only to the global Owner;
- keep workspace selection as a server-side membership-validated POST rather
  than trusting a posted slug, organization ID, or client-side state;
- show single-workspace staff their active workspace and effective title without
  a switch control;
- label Pendang workspace authority explicitly in the Forest Fieldbook UI so
  `workspace_owner` is not confused with global MARK-OS Owner;
- send a Pendang workspace-owner Relationship Manager directly to `/crm`;
- add Owner-side Pendang account presets that fill role/workspace authority but
  never contain a real username or password;
- treat every managed-account creation and Owner password reset as a temporary
  credential;
- force temporary-password users through an authenticated password-change gate
  before otherwise-authorized work;
- verify the current password, require a different valid replacement, increment
  `session_version`, and re-sign only the successful current session;
- preserve existing authorization-denial behavior before applying the
  temporary-password gate.

**Reason:**

- Mark must always know whether CRM actions target MARK Agency or Pendang;
- Rey and Freddy should not have a workspace control when they have only one
  authorized business workspace;
- workspace-owner authority must be understandable without granting or
  suggesting global Owner access;
- source-controlled or reusable staff passwords would undermine the otherwise
  revocable membership model;
- password resets must revoke old sessions while still giving the intended user
  a controlled first-login path.

## 2026-08-07 — Separate global identity from revocable workspace authority

**Decision:**

- keep `users.role` as the stable global application identity and add no second
  global Owner role;
- make `organization_memberships.active` the independently revocable workspace
  access gate;
- calculate CRM owner-like authority from the authenticated global
  `relationship_manager` role plus an active `workspace_owner` membership;
- reserve `workspace_admin` for the current global Owner model;
- constrain Lead Researchers to `crm_contributor`;
- reload global role and active membership from SQLite before consequential CRM
  workflow decisions instead of trusting posted IDs or caller-supplied role
  claims;
- invalidate all existing sessions whenever a workspace membership is granted,
  changed, restored, or revoked;
- preserve historical creator/research/activity attribution when access is
  revoked while returning active assignments to a safe Owner-controlled state;
- never seed real Pendang staff credentials in migrations or source control.

**Reason:**

- Rey needs Pendang owner authority without gaining access to MARK Agency,
  personal/family workspaces, global settings, or private finance;
- Freddy needs a narrow research role that cannot approve its own work or make
  owner-only CRM decisions;
- membership revocation must take effect immediately and must survive ordinary
  application startup;
- separating global identity from workspace authority keeps future business
  workspaces possible without duplicating authentication, databases, or apps.

## 2026-08-07 — Enforce the authenticated workspace through CRM workflows

**Decision:**

- treat `request.state.current_workspace`, resolved from the signed session and
  current organization membership, as the runtime CRM organization boundary;
- require a resolved workspace on CRM dashboard, lead intake, import, lead
  detail, research, activity, follow-up, pipeline, next-action, and relationship
  management paths;
- pass the resolved organization ID into CRM services rather than loading a lead
  globally and filtering afterward;
- make cross-workspace lead URLs return the same safe not-found behavior as an
  inaccessible lead;
- require explicit organization membership in role-aware queues and
  actor-sensitive workflow services whenever runtime organization context is
  supplied;
- keep a MARK Agency compatibility fallback only for older direct service/unit
  callers that do not yet pass organization context; real middleware-backed CRM
  requests always pass an explicit workspace;
- backfill only legacy active CRM staff who have **no** organization membership
  into MARK Agency, leaving explicitly scoped accounts unchanged;
- let staff-creation services accept an explicit workspace while keeping the
  existing Owner UI's default behavior compatible with MARK Agency;
- do not expand global role permissions in this step.

**Reason:**

- organization-scoped lead identity is insufficient if dashboards, queues,
  research workflows, activities, or direct URLs can still query globally;
- signed-session workspace resolution plus service-level organization predicates
  creates defense in depth against forged IDs and accidental cross-business
  access;
- a narrow legacy membership backfill preserves existing MARK Agency staff
  access without silently adding Pendang access;
- separating isolation from Rey/Freddy authority keeps permission expansion
  reviewable as its own milestone.

## 2026-08-07 — Make lead identity workspace-scoped before route enforcement

**Decision:**

- change active lead semantic uniqueness to
  `(organization_id, dedupe_key) WHERE deleted_at IS NULL`;
- keep existing request keys globally unique for backward-compatible retry
  safety;
- never return a lead from another workspace when a request key collides;
- add organization-aware core lead service paths before changing every CRM
  route and workflow;
- temporarily map legacy callers that do not yet pass organization context to
  MARK Agency only, never to a global/unscoped query;
- migrate all runtime CRM callers to explicit authenticated workspace context
  in Phase 6.6B-4B, then remove reliance on the compatibility fallback;
- preserve linked quests, request fingerprints, soft deletion, existing IDs,
  and existing CRM workflow behavior.

**Reason:**

- a global semantic duplicate rule incorrectly prevents the same company or
  contact from existing independently in MARK Agency and Pendang;
- separating the database/service identity boundary from route propagation
  keeps the migration reviewable and reduces the risk of mixing permission,
  workflow, and schema changes in one commit;
- the temporary MARK Agency compatibility scope keeps legacy tests and current
  MARK Agency behavior deterministic while ensuring the core service never
  performs a global lead lookup.

## 2026-08-07 — Adopt the Orbit-inspired Forest Fieldbook visual system

**Decision:**

- keep the existing FastAPI, Jinja, HTMX, Bulma, SQLite, and server-rendered
  MARK-OS architecture;
- add a Forest Fieldbook visual layer inspired by Orbit's human-centered
  notebook interface;
- use warm paper surfaces, deep pine navigation, moss/fern accents, subtle
  paper texture, irregular borders, and solid offset shadows;
- use small sticky-note treatments for dashboard metrics while keeping tables,
  forms, permissions, dates, and CRM records visually stable and unrotated;
- use tactile button press states without changing route or HTMX behavior;
- add a read-only workspace context strip before Phase 6.6B workspace switching
  is implemented;
- preserve the existing responsive CRM hero contract, accessibility focus
  states, and reduced-motion behavior;
- record Orbit as design inspiration in `THIRD_PARTY_NOTICES.md`;
- do not copy Orbit's Astro/Preact runtime, Markdown database, or task
  drag-and-drop architecture.

**Reason:**

- MARK-OS should feel like a human-owned field notebook rather than a generic
  enterprise or AI dashboard;
- the visual language gives MARK Agency and Pendang a memorable shared shell
  before organization-scoped CRM UI is completed;
- controlled irregularity adds personality without sacrificing operational
  readability;
- the read-only workspace strip makes organization context visible without
  prematurely introducing authorization-sensitive switching behavior.

## 2026-08-07 — Adopt a calm operational frontend baseline

**Decision:**

- use the repo-local `mark-os-ui` and `mark-os-htmx` skills as the frontend
  review contract;
- keep FastAPI, Jinja, HTMX, Bulma, and project-owned CSS;
- simplify the application from a glowing, marketing-like dashboard treatment
  toward a calmer operations interface;
- remove the decorative grid overlay and reduce gradients, glow, large shadows,
  oversized radii, and excessive uppercase treatment;
- preserve the existing sidebar information architecture;
- use clearer focus states, calmer dark controls, restrained status surfaces,
  and reduced-motion support;
- shorten CRM headings and descriptive copy so the page emphasizes business
  state and actions;
- make sign-in copy generic for all authorized MARK-OS users rather than
  addressing Mark specifically;
- keep the existing responsive CRM hero contract and make the visual pass work
  at the content width left by the sidebar.

**Reason:**

- MARK-OS is now a multi-user operating tool rather than a single-user visual
  prototype;
- the existing green glow, grid background, large rounded surfaces, and
  marketing copy compete with CRM information;
- Rey, Freddy, Mark, and future staff need predictable operational screens
  more than decorative presentation;
- a shared CSS baseline reduces future one-off styling and gives Phase 6.6
  workspace UI a stable foundation.

## 2026-08-06 — Keep CRM hero copy independent from action width

**Decision:**

- replace the Bulma two-column CRM hero with a dedicated responsive grid;
- stack CRM copy and actions at ordinary sidebar-constrained desktop widths;
- use two columns only when at least 1180 pixels remain for the application
  content;
- allow action buttons to wrap without shrinking the headline into
  character-sized columns;
- apply the same layout contract to Client Hunting and the Follow-up Command
  Center;
- keep normal word-breaking and disable forced headline hyphenation;
- make CRM actions full-width on small mobile screens;
- bump the frontend stylesheet query version so Railway browsers do not retain
  the broken cached layout.

**Reason:**

- the sidebar reduces the available application width even on a desktop
  monitor;
- four CRM actions made Bulma's narrow action column consume most of the hero,
  leaving the flexible headline column too narrow for complete words;
- the defect was visual and responsive, not a data or route failure;
- sharing one hero contract prevents the Follow-up Command Center from
  developing the same problem as more actions are added.

## 2026-08-06 — Count errors from bounded Railway JSON exports

**Decision:**

- make Railway-captured standard-output JSON the lightweight source for the
  previous-24-hour application-error count;
- add the Railway-required `message` field while retaining the stable `event`
  field and existing safe structured attributes;
- parse both direct MARK-OS JSON lines and Railway JSON wrappers whose `message`
  contains the original application event;
- count only `mark_os.application` records with error or critical severity
  inside an inclusive, timezone-aware bounded window;
- report counts by event, unique correlation IDs, and at most a small allowlisted
  set of recent samples;
- exclude arbitrary payload fields, traceback details, usernames, request bodies,
  credentials, paths outside the request URL, deployment identifiers, and raw
  network messages from the generated summary;
- keep the report as a local/CLI review tool rather than adding another database
  table, background worker, or paid monitoring platform;
- document current Railway CLI commands for application errors, HTTP 5xx
  responses, and correlation-ID investigation in `PROJECT.md`.

**Reason:**

- Railway already retains and filters standard-output logs, so duplicating them
  into SQLite would create storage, retention, migration, and privacy work;
- a bounded parser supplies the required daily count while remaining useful with
  manually exported or piped logs;
- allowlisted samples give Mark enough context to investigate without recreating
  sensitive raw logs;
- preserving both `message` and `event` improves Railway compatibility without
  changing the application's stable event taxonomy.

## 2026-08-06 — Separate web readiness from scheduled operations monitoring

**Decision:**

- make `/health` verify that the configured SQLite file is readable and
  initialized, returning HTTP 503 with generic details when it is not;
- keep backup freshness out of the Railway readiness decision so one stale
  backup does not create a web-service restart loop;
- add `tools/check_operations.py` as the single scheduled check for both the
  public `/health` endpoint and the verified Phase 6.2 backup directory;
- classify backup failures as missing, stale, or invalid without placing
  database paths or verification exception text in alerts;
- support one optional Discord-compatible Owner webhook through
  `MARK_OS_OWNER_ALERT_WEBHOOK_URL`;
- remove query strings and embedded credentials from checked URLs before use;
- never include the webhook URL, database path, backup path, or raw network
  exception message in structured events or Owner alerts;
- return a non-zero command status whenever uptime or backup verification fails.

**Reason:**

- Railway should restart MARK-OS when the application database is unavailable,
  but not repeatedly restart a healthy web process because a scheduled backup
  is late;
- one scheduled command is easier and cheaper to operate than a monitoring
  platform;
- the existing Phase 6.2 backup verifier remains the source of backup truth;
- a Discord webhook is free, simple, revocable, and does not require storing an
  email password or adding a paid SDK;
- generic alerts provide enough information to investigate in Railway logs
  without leaking operational paths or secrets.

## 2026-08-06 — Use one structured application logger and safe correlation IDs

**Decision:**

- create one JSON logger named `mark_os.application`, separate from Uvicorn
  access logs;
- emit structured events to standard output so Railway can collect them without
  a paid monitoring SDK;
- accept `X-Request-ID` only when it is short and restricted to safe characters,
  otherwise generate a UUID-based correlation ID;
- include the correlation ID on every response and bind it through a context
  variable for route and service events;
- log startup, authentication, authorization, cross-site security, unhandled
  application, and explicit 5xx-response events;
- log only method, path, status, database-backed user ID and role, event fields,
  exception type, and traceback frame locations;
- exclude query strings, request bodies, passwords, cookies, authorization
  headers, session values, usernames, display names, and exception messages;
- return a generic 500 response while retaining browser security headers.

**Reason:**

- Railway already captures standard output, so JSON events create immediate
  production visibility without another service or recurring cost;
- correlation IDs let Mark connect a user-visible failure to one log event;
- strict request-ID validation prevents log injection and oversized attacker
  input;
- exception messages and request payloads may contain credentials or personal
  data and are not required for the first observability baseline;
- preserving a separate application logger keeps operational errors distinct
  from high-volume access logs.

## 2026-08-06 — Complete the Follow-up Command Center after acceptance verification

**Decision:**

- close Phase 6.4 only after service, route, template, navigation, and role-scoped
  rendering have passed together;
- verify Lead Researcher and Relationship Manager isolation through the rendered
  page, including filter-option names and visible-record counts;
- verify the exact UTC instant at which the Manila operational date changes;
- verify the five-day stale-contact cutoff on both sides of Manila midnight;
- verify all ten empty queues remain visible with explicit operational copy;
- verify command-center service and rendering paths do not mutate leads,
  activities, quests, XP state, or the XP ledger;
- keep the completed command center read-only and route all writes through
  existing lead-detail workflows.

**Reason:**

- unit-level visibility checks are insufficient if templates or filter choices
  later reveal foreign names, counts, or links;
- date rules must remain stable when Railway runs in UTC;
- an empty command center is still actionable information;
- a read-only dashboard must be proven not to create hidden CRM or gamification
  side effects;
- the acceptance matrix establishes a safe baseline before observability work
  changes middleware and error handling.

## 2026-08-06 — Keep the Follow-up Command Center read-only and visibility-scoped

**Decision:**

- expose the deterministic Phase 6.4 queue service at `/crm/follow-ups`;
- allow Owner, Lead Researcher, and Relationship Manager access through the
  existing CRM request matrix;
- keep the page read-only and send every action to the existing lead-detail
  workflow;
- show all required queue cards even when empty, with explicit safe empty-state
  copy;
- expose assignee, researcher, and Business Development Owner filters only from
  the actor's already-visible lead set;
- keep date calculations and queue membership in the service layer rather than
  duplicating them in templates or routes.

**Reason:**

- a command center should summarize operational truth, not create a second write
  path;
- linking to lead detail preserves existing approval, activity, correction, and
  pipeline permission checks;
- empty queues are meaningful operational signals and must not disappear;
- visibility-scoped filter options prevent names and record counts from leaking
  across staff boundaries;
- thin routes and presentation-only templates keep queue rules independently
  testable.

## 2026-08-06 — Define deterministic follow-up date semantics

**Decision:**

- use `Asia/Manila` as the operational timezone for command-center date
  boundaries;
- calculate the effective due date from the latest non-deleted activity carrying
  `next_follow_up_date`, falling back to the lead's `next_action_due_date`;
- calculate last contact from the latest non-deleted external activity, so later
  internal research notes do not hide the prospect's actual contact state;
- define Due This Week as dates after today through Sunday;
- define stale contact as Contacted-or-later with no external contact in the
  previous five Manila dates;
- reload the actor from the database before applying the existing CRM visibility
  rules;
- apply assignee, researcher, and Business Development Owner filters only after
  role-scoped visibility has been established.

**Reason:**

- activity follow-up is the more specific operational commitment once contact
  history exists;
- internal activity must not falsely reset a prospect-contact timer;
- explicit timezone and week boundaries prevent server-local and Railway-UTC
  differences;
- database-backed role truth prevents forged mappings from widening CRM access;
- filtering an already-scoped set prevents count and record leakage.

## 2026-08-06 — Make Contacted a dedicated atomic audit transition

**Decision:**

- require an explicit outbound activity type, contact date and time, external
  channel, message summary, responsible CRM user, response status, and next
  follow-up date whenever a lead first moves to `contacted`;
- insert the contact activity and update the pipeline inside one workflow
  transaction;
- keep the original activity service as the only validated write path;
- remove `contacted` from ordinary create/edit and quick-stage selectors unless
  the lead is already in that state;
- block the full Owner edit service from creating a new Contacted transition;
- treat a repeated `contacted` submission as an idempotent no-op rather than
  writing a duplicate activity.

**Reason:**

- pipeline status alone cannot prove that outreach happened or identify who must
  follow up;
- a dedicated form makes all required audit fields visible before the
  consequential transition;
- one transaction prevents a Contacted lead without its activity and prevents an
  orphan activity when the pipeline update fails;
- explicit activity type is safer than inferring business meaning from the
  channel;
- Phase 6.13 can later reuse this audit foundation without granting blanket
  staff authority.

## 2026-08-06 — Keep staff activity permissions narrow until delegated outreach

**Decision:**

- reload every activity actor from the database by user ID instead of trusting a
  caller-supplied role;
- convert the database row to a plain mapping before using shared permission
  helpers;
- allow Lead Researchers to append and correct only their own internal research
  lifecycle activities on leads already visible to them;
- allow Relationship Managers to read the timeline for leads in their existing
  Business Development scope, but do not grant outbound activity creation in
  Phase 6.3;
- reserve outbound activity creation, cross-user performer attribution, deleted
  history review, restoration, and unrestricted correction for the Owner;
- use the same not-found service result for missing and non-visible lead or
  activity records.

**Reason:**

- Phase 6.3 creates the audit mechanism, while Phase 6.13 is the explicit,
  revocable delegated-outreach permission gate;
- shared access-control helpers accept mapping-shaped users, so normalizing the
  database row at the service boundary preserves one permission contract;
- trusting the database role prevents forged service calls from escalating a
  staff user's permissions;
- preserving narrow role permissions keeps outreach approval and delegation
  separate and auditable;
- a uniform not-found result prevents cross-user record enumeration.

## 2026-08-06 — Define CRM activity ownership and audit retention

Decision:

- store lead activity history in a separate `lead_activities` table;
- scope activities through the associated lead and existing CRM visibility rules
  rather than adding personal-workspace `user_id` ownership;
- preserve separate author, performer, responsible-user, and correcting-user
  attribution;
- restrict physical deletion of referenced leads and actor accounts while audit
  records exist;
- require an identified correcting user and a non-empty reason for corrections
  and soft deletions.

Reason:

- CRM activities are collaborative business records rather than private personal
  workspace records;
- author, performer, and follow-up responsibility are different facts and must
  not be overloaded;
- deactivation is safer than physical deletion for staff accounts that appear in
  the sales audit trail;
- Phase 6.4 follow-up calculations and Phase 6.13 delegated outreach depend on
  durable, attributable activity history.

## 2026-08-05 — Complete Phase 6.1J and promote production safety

Decision:

- mark Phase 6.1A–6.1J complete;
- recognize Owner, Lead Researcher, and Relationship Manager as operational
  production roles;
- make Backup and Disaster Recovery the immediate next milestone;
- renumber remaining agency work by execution priority;
- move Observability and deterministic outreach templates into Phase 6;
- keep trigger-based business lifecycle work after the operational foundation.

Reason:

- Railway now stores real accounts, leads, approvals, ownership, and an
  internal sales playbook;
- production data loss is now a larger risk than delaying another CRM feature;
- activity history must exist before delegated outreach;
- follow-up calculations depend on activity history;
- monitoring is required before more staff depend on the application;
- the new numbering should reflect the actual build order.

### New immediate sequence

```text
Phase 6.2  Backup and Disaster Recovery
Phase 6.3  Lead Activity Timeline
Phase 6.4  Follow-up Command Center
Phase 6.5  Observability and Error Monitoring
Phase 6.6  Bulk Lead Management
Phase 6.7  Outreach Templates and Approval Controls
Phase 6.8  Effort Tracking and Webhook Intake
```

## 2026-08-05 — Consolidate project documentation

Decision:

- create one canonical `PROJECT.md`;
- stop creating separate handoff and roadmap Markdown files;
- treat older documents as historical sources;
- update only this file for future phases.

Reason:

- several documents describe different project ages;
- old single-user statements conflict with the M10 repository;
- old Phase 5 numbering conflicts with new priorities;
- one source reduces confusion.

## 2026-08-05 — Prioritize agency operations and settle phase numbering — Condensed

Across several 2026-08-05 decisions, Phase 6 was retargeted from "Product
Hardening" to "Agency Operations and Production Safety" (brother/staff
usability was not yet operationally complete and created immediate business
risk), Phases 7–9 were renumbered to Product Hardening, Budget-Safe AI, and
Affordable Ambient Assistant respectively, and effort tracking/staging/
observability work was distributed into Phases 6.5, 6.8, and 7.6. These
decisions were superseded by the 2026-08-05 "Complete Phase 6.1J" reprioritization
below; the current authoritative phase numbering is maintained in Section 12.

## 2026-08-05 — Add delegated outreach permission phase

Decision:

- add delegated outreach as the trigger-based Phase 6.13;
- require Phase 6.3 activity logging first;
- implement a narrow, revocable, per-user `can_contact_leads` permission;
- apply it primarily to a trusted `relationship_manager`, not as a role-wide
  default;
- preserve Owner control over approval, pricing, proposals, Won/Lost,
  reassignment, deletion, and finance.

Reason:

- the initial workflow correctly keeps outreach and stage transitions
  Owner-controlled;
- Junmar's playbook requires complete contact records;
- trusted staff outreach must be traceable and immediately revocable without
  granting broad Owner authority.

## 2026-08-05 — Add an affordable Ambient Assistant phase

Decision:

- add Phase 9 — Affordable Ambient Assistant;
- place it after the Phase 8 intent router, budget gate, and confirmed-action
  protections;
- use browser speech, deterministic nudges, local wake-word processing, and
  low-cost channels before paid providers;
- keep Phase 9 spending inside the existing PHP 200 monthly AI cap;
- prefer Telegram and Discord, while deferring SMS because of direct
  per-message cost.

Reason:

- browser speech and deterministic reminders provide most of the useful
  "Jarvis" experience without additional model calls;
- proactive behavior should come from stored data and rules, not constant
  background prompting;
- voice and external channels must not bypass permissions or confirmation;
- the assistant should continue functioning when AI spending reaches its
  monthly limit.

---

## 2026-08-05 — Park backup work — Superseded

Superseded by the completion of Phase 6.1J: backup work became Phase 6.2 and
the active milestone once the staff-workflow blocker was resolved and
production held more valuable operational data.

---

# 20. Documentation and Operations Runbooks

## 20.1 Canonical documentation policy

The repository uses two human-facing project documents:

```text
README.md   # short public entry point and local quick start
PROJECT.md  # canonical detailed project and operations guide
```

Repository-specific coding-agent instructions remain separate because they are
executable project constraints rather than duplicate product documentation:

```text
AGENTS.md
.agents/skills/README.md
.agents/skills/mark-os-ui/SKILL.md
.agents/skills/mark-os-ui/DESIGN.md
.agents/skills/mark-os-htmx/SKILL.md
```

`THIRD_PARTY_NOTICES.md` remains separate for attribution.

Do not create new phase-specific install, roadmap, release-runbook, or handoff
Markdown files. When durable project information changes, update `PROJECT.md`.
Temporary release evidence belongs outside Git.

## 20.2 Historical release verifiers that remain useful

The old phase-specific installation documents are retired, but their verifier
tools remain useful when reviewing legacy data or reproducing an older release
boundary.

### Family workspace verification

```bash
python tools/verify_m10_family_release.py
```

The verifier checks personal ownership, role boundaries, workspace integrity,
and per-user uniqueness. Personal tables should report no unowned or orphaned
records.

### Phase 6.1 staff-workflow staging verification

Never run migration rehearsal against the live Railway database. Use a verified
snapshot or backup:

```bash
python tools/verify_phase_6_1_release.py \
  --source-db /path/to/safe-snapshot.sqlite3 \
  --run-tests
```

The verifier creates a staging copy, runs migrations and workflow canaries on
the copy, checks integrity and foreign keys, and preserves the supplied source.

### Relationship Manager / playbook verification

Private sales playbooks remain outside Git. Import or update an approved local
playbook through the existing importer:

```bash
python tools/import_playbook.py \
  --file private_playbooks/JUNMAR_SALES_PLAYBOOK.md \
  --slug junmar-sales-playbook \
  --assign-username junmar
```

For a safe copied-database check:

```bash
python tools/verify_phase_6_1j_release.py \
  --source-db /path/to/safe-snapshot.sqlite3 \
  --output-dir "$HOME/mark-os-release-evidence"
```

Do not commit private playbook Markdown or generated release evidence.

## 20.3 Standard release and rollback procedure

Before a production deployment:

```bash
git status
git log -1 --oneline
python -m pytest -q
```

Confirm:

```text
working tree clean
full suite passed
database migration rehearsal passed when schema changed
verified rollback backup exists
Railway uses exactly one application instance while SQLite is production
persistent-volume database path is confirmed
```

After deployment verify:

```text
/health returns HTTP 200
Owner login works
role-specific login and navigation work
workspace isolation still holds
one non-destructive CRM read/smoke check succeeds
production logs show no new migration/startup failure
```

### Application-code rollback

When the database remains healthy and a deployment has only an application or
template defect:

1. stop staff activity temporarily;
2. record the failing deployment commit;
3. redeploy the last known-good application commit;
4. do not restore the database merely because application code was rolled back;
5. verify `/health`, login, workspace selection, and CRM read access;
6. preserve failed-state logs and evidence for diagnosis.

### Database rollback

Restore a database only for verified data corruption or a failed migration that
changed production data incorrectly. Signals include a failed
`PRAGMA quick_check`, foreign-key errors, or confirmed damaged records.

Before replacing production data:

1. stop application/staff writes;
2. capture one final backup of the failed state;
3. record its checksum and deployment commit;
4. verify the selected recovery backup;
5. restore into a **new filename**;
6. inspect and smoke-test that restored database;
7. switch `MARK_OS_DB_PATH` only after verification;
8. retain both old and recovered databases until the incident is closed.

## 20.4 Phase 6.2 backup and disaster recovery runbook

MARK-OS production protection has three complementary layers:

```text
Railway volume snapshots
+ verified SQLite online backups
+ encrypted offsite copies
```

A backup is not proven until a restore into a new file succeeds.

### Non-negotiable SQLite backup rules

1. Never use plain `cp` on the live SQLite database while MARK-OS is running.
2. Use SQLite's online backup API through `tools/backup_database.py`.
3. Never restore directly over the configured live database file.
4. Restore to a new filename, verify it, then switch `MARK_OS_DB_PATH` in a
   controlled deployment.
5. Keep at least one encrypted copy outside the Railway volume.
6. Railway volume snapshots and logical SQLite backups complement each other.

### Local backup and restore proof

Create a backup:

```bash
python tools/backup_database.py
```

Find and verify the newest backup:

```bash
LATEST_BACKUP="$(ls -t data/backups/mark_os_*.sqlite3 | head -1)"
echo "$LATEST_BACKUP"

python tools/verify_database_backup.py \
  --backup "$LATEST_BACKUP"
```

Restore into a new local database:

```bash
rm -f data/restore-test.sqlite3

python tools/restore_database.py \
  --backup "$LATEST_BACKUP" \
  --destination data/restore-test.sqlite3
```

Start a temporary restored instance:

```bash
MARK_OS_DB_PATH="$PWD/data/restore-test.sqlite3" \
uvicorn --env-file .env app.main:app \
  --host 127.0.0.1 \
  --port 8001
```

Verify `/health`, login, Users, CRM, workspace isolation, then stop the
temporary instance.

Automated release proof:

```bash
python tools/verify_phase_6_2_release.py \
  --source-db data/mark_os.db \
  --output-dir "$HOME/mark-os-release-evidence" \
  --run-tests
```

Expected final status:

```text
Phase 6.2 verification PASSED
```

### Railway volume snapshot layer

In Railway, keep the volume and database path aligned:

```text
RAILWAY_VOLUME_MOUNT_PATH=/app/data
MARK_OS_DB_PATH=/app/data/mark_os.db
MARK_OS_BACKUP_DIR=/app/data/backups
```

Create and retain a known-good manual volume snapshot and keep scheduled volume
backups enabled. Volume snapshots are the preferred whole-volume rollback
mechanism.

### Railway verified SQLite online backup

Link the CLI and open SSH:

```bash
railway login
railway link
railway service
railway ssh
```

Inside Railway:

```bash
cd /app

echo "$MARK_OS_DB_PATH"
echo "$RAILWAY_VOLUME_MOUNT_PATH"

python tools/backup_database.py \
  --destination /app/data/backups \
  --keep-last 14

python tools/backup_status.py \
  --directory /app/data/backups \
  --max-age-hours 26
```

Copy the exact backup and manifest names printed by the command, then exit:

```bash
exit
```

Download both files:

```bash
mkdir -p "$HOME/mark-os-offsite/plaintext"

railway service files download \
  /app/data/backups/EXACT_BACKUP.sqlite3 \
  "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3"

railway service files download \
  /app/data/backups/EXACT_BACKUP.sqlite3.json \
  "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3.json"
```

Verify locally:

```bash
python tools/verify_database_backup.py \
  --backup "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3"
```

The backup filename must continue to match the manifest.

### Encrypted offsite copy

Install GnuPG once on macOS:

```bash
brew install gnupg
```

Encrypt a verified downloaded backup:

```bash
mkdir -p "$HOME/mark-os-offsite/encrypted"

python tools/encrypt_backup.py \
  --backup "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3" \
  --output "$HOME/mark-os-offsite/encrypted/EXACT_BACKUP.sqlite3.gpg"
```

Keep the `.gpg`, `.gpg.sha256`, and manifest in an offsite encrypted location.
Never store the passphrase beside the backup.

Test decryption before deleting plaintext:

```bash
gpg \
  --output "$HOME/mark-os-offsite/restore-check.sqlite3" \
  --decrypt "$HOME/mark-os-offsite/encrypted/EXACT_BACKUP.sqlite3.gpg"

cp \
  "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3.json" \
  "$HOME/mark-os-offsite/restore-check.sqlite3.json"

python tools/verify_database_backup.py \
  --backup "$HOME/mark-os-offsite/restore-check.sqlite3"
```

If a temporary decrypted filename differs from the manifest filename, restore
using the original filename in a temporary directory or follow the backup tool's
manifest-validation rules. Do not weaken checksum verification merely to make a
renamed file pass.

### Production recovery from a logical SQLite backup

Never overwrite `/app/data/mark_os.db` directly.

On the Mac:

```bash
python tools/restore_database.py \
  --backup "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3" \
  --destination "$HOME/mark-os-offsite/mark_os_recovered.sqlite3"
```

Upload the recovered file into a separate Railway path:

```bash
railway service files upload \
  "$HOME/mark-os-offsite/mark_os_recovered.sqlite3" \
  /app/data/restores/mark_os_recovered.sqlite3
```

Change the Railway variable to the recovered path:

```text
MARK_OS_DB_PATH=/app/data/restores/mark_os_recovered.sqlite3
```

Redeploy and verify `/health`, users, CRM records, playbooks, and workspace
isolation. Roll back by switching `MARK_OS_DB_PATH` to the previous verified
file. Do not delete either database until the recovery decision is final.

### Backup freshness and failure visibility

Logical backup events are recorded under the configured backup directory.
Check freshness and integrity:

```bash
python tools/backup_status.py \
  --directory /app/data/backups \
  --max-age-hours 26
```

A non-zero result means the backup is missing, stale, corrupt, or inconsistent
with its manifest and must be investigated.

Keep completion evidence outside Git:

```text
full pytest result
verification JSON report
Railway snapshot date/evidence
downloaded SQLite backup + manifest
encrypted offsite copy + checksum
successful decrypt-and-restore test
recovery target path
rollback path
```

## 20.5 Google Drive offsite backup extension

The Google Drive extension uses the existing verified SQLite backup service and
`tools/backup_to_google_drive.py`.

### Local rclone setup

Install rclone:

```bash
brew install rclone
rclone config
```

Recommended remote configuration:

```text
Remote name: gdrive
Storage: drive
Client ID: your own Google OAuth desktop client ID
Client secret: your own Google OAuth client secret
Scope: drive.file
Service account: blank
Browser authorization: yes
Shared Drive: no
```

Create the backup folder with rclone so `drive.file` can access it:

```bash
rclone mkdir gdrive:MARK-OS-Backups
rclone lsd gdrive:
```

Test locally:

```bash
python tools/backup_to_google_drive.py \
  --source "$PWD/data/mark_os.db"
```

### Railway configuration

The Railway runtime needs rclone available:

```text
RAILPACK_DEPLOY_APT_PACKAGES=rclone
```

Application variables:

```text
MARK_OS_GDRIVE_REMOTE=gdrive
MARK_OS_GDRIVE_FOLDER=MARK-OS-Backups
MARK_OS_GDRIVE_KEEP_LAST=14
MARK_OS_BACKUP_PREFIX=mark_os
```

Transfer the values from `rclone config show gdrive` into sealed Railway
variables:

```text
RCLONE_CONFIG_GDRIVE_TYPE=drive
RCLONE_CONFIG_GDRIVE_CLIENT_ID=<client id>
RCLONE_CONFIG_GDRIVE_CLIENT_SECRET=<client secret>
RCLONE_CONFIG_GDRIVE_SCOPE=drive.file
RCLONE_CONFIG_GDRIVE_TOKEN=<complete token JSON>
```

Never commit the rclone configuration, OAuth client secret, or token.

### Railway manual test

```bash
railway ssh
```

Inside Railway:

```bash
cd /app
rclone version
rclone lsd gdrive:

python tools/backup_to_google_drive.py \
  --source /app/data/mark_os.db

rclone lsl gdrive:MARK-OS-Backups
```

A successful run must verify the remote transfer and remove temporary Railway
backup files.

### Scheduling constraint

The production SQLite volume belongs to the MARK-OS web service. Do not assume
a separate cron service can directly read that mounted volume.

The documented safe future automation pattern is:

```text
Railway cron service
        |
        | authenticated request
        v
MARK-OS web service protected backup endpoint
        |
        +-- reads /app/data/mark_os.db
        +-- creates verified temporary backup
        +-- uploads to Google Drive
        +-- removes temporary files
```

Add such an endpoint only as a separate reviewed capability. The current manual
Google Drive backup procedure does not require it.

## 20.6 Documentation cleanup history

The following legacy documents were consolidated into this section and removed
from the repository after their durable information was preserved:

```text
M10_INSTALL.md
PHASE_6_1J_INSTALL.md
PHASE_6_1_HI_RELEASE_RUNBOOK.md
PHASE_6_2_BACKUP_RECOVERY.md
PHASE_6_2_GOOGLE_DRIVE.md
```

Historical installer packaging commands, obsolete expected test counts, and
one-time branch/ZIP extraction instructions were intentionally not retained.
Git history remains the source for those implementation-era details.

---

# 21. Final Operating Principle

MARK-OS should become more capable without becoming less understandable.

Every new capability must preserve:

```text
clear ownership
+ deterministic rules
+ permission boundaries
+ complete history
+ safe migrations
+ reversible operations
+ tests
+ controlled cost
```

The immediate focus is simple:

```text
Make Mark and his brother effective at finding,
reviewing, following up with, and winning clients.
```
