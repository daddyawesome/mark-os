# MARK-OS — Complete Project Guide and Roadmap

**Canonical project document**  
**Repository:** `https://github.com/daddyawesome/mark-os`  
**Reviewed against `main`:** 2026-08-06
**Current active phase:** Phase 6 — Agency Operations and Production Safety  
**Immediate next milestone:** Phase 6.6A — Bulk Lead Import Preview and Row Validation
**Production deployment:** Railway  
**Primary database:** SQLite on a persistent Railway volume  
**Last verified full-suite baseline:** 449 passed after Phase 6.5

---

## 1. Purpose of This Document

This file is the single source of project documentation for MARK-OS.

It consolidates and supersedes the detailed content previously spread across:

```text
README.md
INSTALL.md
docs/AI_ARCHITECTURE.md
docs/AI_ARCHITECTURE_V2.md
docs/CODEX_CONTINUE_MARK_OS_PHASE_5.md
docs/MARK_OS_COMPLETE_PROJECT_HANDOFF.md
docs/PHASE_4_REVISED_DOD.md
docs/PROJECT_ROADMAP.md
```

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
standalone roadmap or handoff document.

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
├── docs/
├── tests/
├── .env.example
├── .gitignore
├── INSTALL.md
├── README.md
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

| Requirement | Next phase |
|---|---|
| Tested production backup and restore process | Phase 6.2 |
| Due, overdue, waiting, and stale-lead command center | Phase 6.4 |
| Production health and error alerts | Phase 6.5 |
| Safe bulk preview, assignment, import, and export | Phase 6.6 |
| Deterministic approved outreach templates | Phase 6.7 |
| Research effort and webhook intake | Phase 6.8 |
| Discovery, proposal, onboarding, and billing workflows | Trigger-based Phases 6.9–6.12 |
| Delegated Relationship Manager outreach | Trigger-based Phase 6.13 |

The next priority is Phase 6.6 Bulk Lead Management. The production system now
has verified backup, auditable activity, deterministic follow-up, and lightweight
observability, so the next business need is safe high-volume lead intake with
preview, row validation, duplicate warnings, and permission-scoped assignment.

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
| Phase 6.6 | Phase 6.10 | Proposal Management |
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

## Phase 6.6 — Bulk Lead Management

**Status:** Active — immediate next milestone
**MoSCoW:** Should have soon

### Goal

Allow staff to research and import many leads without unsafe blind writes.

### Workflow

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
- selective import;
- bulk researcher assignment;
- bulk Business Development Owner assignment;
- bulk submission for review;
- permission-scoped CSV and JSON export;
- approved-leads export;
- downloadable CRM backup.

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

- Phase 6.6 bulk preview, validation, assignment, import, and export;
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
| Phase 6.6 | Active — immediate next milestone | Bulk Lead Management |
| Phase 6.7 | Should soon | Outreach Templates and Approval Controls |
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

## 2026-08-05 — Make brother usability the first priority

Decision:

- park Product Hardening temporarily;
- make Agency CRM Operations the new Phase 6;
- make Staff Workflow and Approval Phase 6.1.

Reason:

- existing multi-user foundations are present;
- the brother workflow is not operationally complete;
- collaboration errors can damage outreach;
- this work creates immediate business value.

## 2026-08-05 — Renumber future phases

Decision:

```text
Phase 6 = Agency Operations and Production Safety
Phase 7 = Product Hardening and Growth
Phase 8 = Budget-Safe AI Continuation
Phase 9 = Affordable Ambient Assistant
```

The detailed Phase 6 milestones were later reordered by execution priority;
the current mapping is maintained in Section 12.

Reason:

- keep completed Phase 5 history intact;
- separate operational agency work from optional AI work;
- place production safety beside the agency workflows it protects;
- keep one chronological roadmap without overlapping active phase numbers.

## 2026-08-05 — Add effort tracking, staging, and observability

Decision at the time:

- introduce effort tracking and webhook intake;
- introduce staging and rollback work;
- introduce observability and error monitoring.

Current numbering after reprioritization:

```text
Phase 6.5  Observability and Error Monitoring
Phase 6.8  Lead-Sourcing Effort Tracking and Webhook Intake
Phase 7.6  Formal Staging Environment and Rollback
```

Reason:

- delivery-cost tracking does not measure pre-client research effort;
- webhook intake removes repetitive CSV work without requiring AI;
- permission and schema changes need a repeatable staging and rollback path;
- production failures must be visible before staff report them.

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

Decision:

- this decision is superseded by the completion of Phase 6.1J;
- backup work is now Phase 6.2 and is the active milestone;
- any useful prior backup code may still be reused after review.

Reason:

- the staff workflow blocker has been resolved;
- production now contains more valuable operational data;
- backup and verified restore are therefore the immediate priority.

---

# 20. Documentation Consolidation Plan

After reviewing and committing this file, make it the canonical detailed
documentation.

Recommended repository arrangement:

```text
README.md       # short public introduction with a link to PROJECT.md
PROJECT.md      # all detailed project documentation
```

The old detailed files can then be removed after confirming that no unique
information is missing.

Suggested cleanup candidates:

```text
INSTALL.md
docs/AI_ARCHITECTURE.md
docs/AI_ARCHITECTURE_V2.md
docs/CODEX_CONTINUE_MARK_OS_PHASE_5.md
docs/MARK_OS_COMPLETE_PROJECT_HANDOFF.md
docs/PHASE_4_REVISED_DOD.md
docs/PROJECT_ROADMAP.md
```

Do not delete them before reviewing the `git diff` for `PROJECT.md`.

A minimal README should retain:

- one-paragraph product description;
- test badge;
- quick local-start commands;
- link to `PROJECT.md`.

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
