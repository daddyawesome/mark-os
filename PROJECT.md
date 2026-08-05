# MARK-OS — Complete Project Guide and Roadmap

**Canonical project document**  
**Repository:** `https://github.com/daddyawesome/mark-os`  
**Reviewed against `main`:** 2026-08-05  
**Current active phase:** Phase 6 — Agency CRM Operations  
**Immediate next milestone:** Phase 6.1 — Staff Workflow, Research Ownership, and Approval  
**Production deployment:** Railway  
**Primary database:** SQLite on a persistent Railway volume  
**Last locally reported test result:** 267 passed

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
workflow that helps Mark and his brother consistently find, review, contact,
and convert leads.

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
├── leads.py
├── memory.py
├── migrations.py
├── quests.py
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
├── gamification.py
├── lead_csv_import.py
├── lead_identity.py
├── leads.py
├── passwords.py
├── personal_scope.py
├── quests.py
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
- lead behavior;
- chat;
- chat migrations;
- agent audit;
- agent-audit migrations;
- quests;
- gamification;
- memory migrations;
- Director behavior;
- sidebar and user navigation.

---

## 6. Current Roles and Access

The backend role values are:

```text
owner
member
lead_sourcer
```

For the agency interface, `lead_sourcer` may be displayed as
**Lead Researcher**, but the stored backend value should remain stable until a
tested migration is intentionally created.

### 6.1 Owner

Mark is the Owner and Founder/Admin.

Current intended access:

- full personal MARK-OS workspace;
- goals, projects, quests, check-ins, XP, history, memory, and chat;
- Client Hunting CRM;
- user management;
- family-member management;
- lead-sourcer management;
- all owner-only settings and administrative actions.

### 6.2 Member

A family member receives a private personal workspace.

Current intended access:

- private dashboard;
- private profile;
- own goals;
- own projects;
- own quests;
- own check-ins;
- own XP and level state;
- own history;
- own memory;
- own chat.

A Member must not access:

- Client Hunting CRM;
- user administration;
- another user's personal records.

### 6.3 Lead Sourcer / Lead Researcher

The current role is intentionally narrow and CRM-only.

Current request access allows:

- open the CRM dashboard;
- open the new-lead form;
- create leads;
- import leads;
- download the import template;
- view lead detail pages;
- log out.

Current important limitation:

The existing route permission list does not yet provide the complete research
editing and approval workflow required for Mark's brother.

That gap is the reason Phase 6.1 is now the active priority.

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
- Lead Sourcers do not receive personal workspace access;
- ownership triggers protect parent/child relationships;
- project names are unique per user;
- memory keys are unique per user;
- each Owner or Member receives one private profile and one game state.

CRM leads use separate collaboration ownership fields:

```text
created_by_user_id
assigned_to_user_id
```

These are not sufficient for the complete research/review process. Phase 6.1
adds the missing staff-workflow fields.

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

#### CRM leads

The current lead schema includes:

```text
id
quest_id
created_by_user_id
assigned_to_user_id
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
- assignee.

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

## 10. Current Gap Analysis for Brother Usability

### Already covered

| Requirement | Current status |
|---|---|
| Separate Mark and brother accounts | Implemented foundation |
| Mark as Founder/Admin | Implemented as `owner` |
| Brother staff role | Implemented foundation as `lead_sourcer` |
| Role-based request permissions | Implemented |
| Brother blocked from personal finance | Implemented through CRM-only access |
| Lead creator tracking | Implemented |
| Lead assignment | Implemented |
| Soft deletion foundation | Implemented |
| CSV import | Implemented |
| Duplicate detection | Implemented |
| Next actions and due dates | Implemented |
| CRM pipeline | Implemented |
| Lead-to-quest linkage | Implemented |

### Missing or incomplete

| Requirement | Gap |
|---|---|
| Brother edits existing research | Current narrow route permissions are incomplete |
| Field-level staff restrictions | Not fully implemented |
| Research status | Missing |
| Researched by | Missing dedicated field |
| Reviewed by | Missing |
| Date reviewed | Missing |
| Review notes | Missing |
| Outreach approval | Missing |
| Major status-change approval | Missing |
| Owner-only pricing changes | Pricing model not yet implemented |
| Owner-only Won/Lost transition | Not yet enforced as a dedicated approval rule |
| Permanent-delete restriction | Soft deletion exists; explicit owner-only purge policy still needed |
| Communication timeline | Missing |
| Operational follow-up queues | Incomplete |
| CSV preview | Missing or incomplete |
| CSV export | Missing |
| Approved-leads export | Missing |
| Bulk assignment | Missing |
| Bulk review submission | Missing |
| In-app CRM backup/download | Missing |

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

---

# 12. Current Official Roadmap

## Numbering decision

The previously proposed Product Hardening phase is parked, not cancelled.

The project numbering is now:

```text
Phase 6 — Agency CRM Operations
Phase 7 — Product Hardening & Growth
Phase 8 — Budget-Safe AI Continuation
```

The old Phase 5.3+ AI work is moved to Phase 8.

The previous Phase 6 Product Hardening work is moved to Phase 7.

This keeps the numbering chronological and removes overlapping active phase
numbers.

---

# Phase 6 — Agency CRM Operations

**Status:** Active  
**Primary objective:** Make MARK-OS operationally usable by Mark and his
brother before adding more advanced systems.

## Phase 6.1 — Staff Workflow, Research Ownership, and Approval

**Status:** Next  
**Priority:** Critical

### Goal

Create a clear workflow so Mark and his brother do not overwrite, duplicate,
misinterpret, or prematurely act on each other's lead work.

### Account model

```text
Mark
Role: Owner
Business title: Founder / Admin

Brother
Backend role: lead_sourcer
Displayed business title: Lead Researcher
```

Keep the backend role value `lead_sourcer` during the first implementation to
avoid unnecessary migration risk.

### Required lead ownership fields

Add or formalize:

```text
assigned_to_user_id
researched_by_user_id
research_status
submitted_for_review_at
reviewed_by_user_id
reviewed_at
review_notes
outreach_approved_by_user_id
outreach_approved_at
```

`created_by_user_id` and `assigned_to_user_id` already exist.

### Research workflow

```text
Draft
→ Researching
→ Ready for Review
→ Changes Requested
→ Approved
→ Rejected
```

Suggested stored values:

```text
draft
researching
ready_for_review
changes_requested
approved
rejected
```

### Brother permissions

Brother can:

- create a lead;
- import leads;
- view assigned or permitted CRM leads;
- edit research fields;
- update research notes;
- submit a lead for review;
- respond to requested changes;
- add research-completed activities.

Brother cannot:

- access private personal finance;
- access family personal workspaces;
- change pricing;
- approve outreach;
- mark a lead Won;
- make major proposal decisions;
- permanently delete a lead;
- change another user's role;
- access Owner administration.

### Mark permissions

Mark can:

- review research;
- request changes;
- approve or reject research;
- approve outreach;
- change major pipeline stages;
- approve proposal-stage decisions;
- mark Won or Lost;
- reassign leads;
- soft-delete duplicate or mistaken leads;
- access all CRM management views.

### Major transition approval

The first version should require Owner permission for:

```text
approved → contacted
meeting → proposal
proposal → won
any state → lost
```

This can be refined after real workflow usage.

### Deletion rule

Use soft deletion for ordinary CRM removal.

Permanent purge should not be available in the normal UI.

### Definition of done

- Brother can log in separately.
- Brother can create and edit permitted research.
- Brother can submit a lead for review.
- Mark can approve, reject, or request changes.
- Review author and timestamps are recorded.
- Brother cannot approve outreach or mark Won/Lost.
- Brother cannot access personal finance.
- Owner-only restrictions are enforced in services, not only hidden in HTML.
- Permission tests cover direct URL and forged POST attempts.
- Existing leads are safely backfilled.
- Existing CSV import still works.
- Full test suite passes.

---

## Phase 6.2 — Lead Activity Timeline

**Priority:** High

### Goal

Store every meaningful interaction instead of only the latest status and next
action.

### New table

Recommended table:

```text
lead_activities
```

Suggested fields:

```text
id
lead_id
activity_type
activity_at
created_by_user_id
notes
next_follow_up_date
created_at
updated_at
deleted_at
```

Activities should normally be append-only.

Corrections should be audited rather than silently replacing history.

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

Display labels may be more readable than stored values.

### Timeline display

Each lead detail page should show:

- activity date and time;
- activity type;
- staff member;
- notes;
- next follow-up date;
- chronological ordering.

### Definition of done

- activity migration is additive;
- timeline is visible on lead detail;
- activity author is preserved;
- next follow-up may be recorded;
- staff permissions are enforced;
- timeline tests pass;
- existing leads remain readable.

---

## Phase 6.3 — Follow-up Command Center

**Priority:** High

### Goal

Provide an in-app operational queue so outreach does not depend on memory.

### Required views

```text
Due Today
Overdue
Due This Week
No Contact for Five Days
Waiting for Reply
Proposal Follow-up Required
Research Awaiting Review
Approved but Not Contacted
```

### Requirements

- counts for every queue;
- sorting by urgency;
- filters by assignee;
- filters by researcher;
- owner view across CRM;
- brother view limited to permitted work;
- activity-based last-contact calculation;
- safe empty-state behavior;
- no email or external notification required.

### Important scope rule

Email, Telegram, Discord, Gmail, and Calendar integrations must not block this
phase.

The first working version is an in-app dashboard.

### Definition of done

- due and overdue logic is deterministic;
- five-day inactivity is calculated from activity history;
- waiting-for-reply and proposal follow-up states are visible;
- owner and brother queues differ correctly by permissions;
- calculations have date-boundary tests.

---

## Phase 6.4 — Bulk Lead Management

**Priority:** High

### Goal

Allow the brother to research and import many leads without slow manual entry.

### Import workflow

```text
Upload CSV
→ parse safely
→ preview rows
→ show valid rows
→ show duplicate warnings
→ show invalid rows
→ select approved rows
→ assign researcher
→ import
```

### Required features

- CSV template;
- CSV import;
- import preview;
- row-level validation;
- duplicate warnings before write;
- row selection;
- bulk assignment;
- bulk submission for review;
- CSV export;
- export approved leads;
- CRM JSON export;
- downloadable CRM backup.

### Scope distinction

This phase covers CRM operational export.

Full personal/family data portability belongs to Phase 7.7.

### Definition of done

- preview does not write to the database;
- duplicate and invalid rows are clearly separated;
- selected valid rows import atomically or with a clear row result;
- exports respect permissions;
- Brother cannot export private finance or family data;
- import/export tests pass.

---

## Phase 6.5 — Discovery and Qualification

**Start condition:** Prospects begin replying or meetings are being booked.

Do not build this before it is operationally needed.

### Required fields

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

### Qualification framework

```text
Problem
→ Business Impact
→ Authority
→ Budget
→ Timing
→ Fit
```

### Definition of done

- qualification data belongs to a lead/opportunity;
- meeting notes are auditable;
- Mark controls final fit and qualification decisions;
- empty fields do not block early-stage leads.

---

## Phase 6.6 — Proposal Management

**Start condition:** Qualified opportunities reach proposal stage.

### Required fields

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

### First-version rule

Do not build a full document generator.

A Google Drive link to the proposal is sufficient.

### Required controls

- Mark approves pricing;
- Mark controls proposal status;
- Brother may add research or notes but cannot change price;
- proposal follow-up appears in the command center;
- accepted and rejected reasons are retained.

---

## Phase 6.7 — Client Onboarding and Delivery

**Start condition:** Client #1 is won.

The agency workflow must continue after Won.

### Full agency loop

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

### Client onboarding

Add:

- client profile;
- primary contacts;
- contract link;
- start date;
- access requirements;
- success criteria;
- communication schedule.

### Projects and delivery

Add:

- deliverables;
- tasks;
- due dates;
- assigned staff;
- client approvals;
- change requests;
- completion evidence.

---

## Phase 6.8 — Retainers, Invoicing, and Profitability

**Start condition:** Active delivery and billing begin.

### Retainer management

Add:

- monthly plan;
- included hours or requests;
- monthly fee;
- renewal date;
- payment status;
- services used;
- out-of-scope requests.

### Agency money tracking

Add:

- revenue;
- invoice amount;
- outstanding invoice;
- payment date;
- contractor/staff cost;
- software cost;
- hours spent;
- estimated profit.

### Security rule

Agency financial data must remain Owner-only unless a future role is explicitly
designed for finance access.

---

# Phase 7 — Product Hardening & Growth

**Status:** Parked  
**Reason:** Agency staff workflow has higher immediate operational value.

Resume this phase after the first four Agency CRM milestones are stable, or
earlier only when a critical production risk requires it.

## Phase 7.1 — Backup and Disaster Recovery

Work already started locally under the previous numbering may be reused.

Planned deliverables:

- safe SQLite online backup;
- timestamped backup files;
- integrity verification;
- checksum and manifest;
- retention;
- restore command;
- restore test;
- Railway persistent-volume backup;
- offsite encrypted backup;
- documented disaster-recovery procedure.

Recommended protection layers:

```text
Live Railway volume
+ Railway scheduled volume backups
+ encrypted offsite backup
+ periodic personal copy
```

Google Drive is acceptable as an offsite location after encryption and secure
credential handling are designed.

## Phase 7.2 — Security and Audit Foundation

Planned deliverables:

- login rate limiting;
- session tracking;
- logout everywhere;
- session revocation;
- admin action audit;
- role-change audit;
- account activation/deactivation audit;
- failed-login events;
- CSRF review;
- secure-cookie review;
- sensitive-log review;
- IDOR regression tests.

Some session-version and security foundations already exist.

## Phase 7.3 — Notifications and Nudges

External delivery may include:

- email;
- Telegram;
- Discord webhook.

Notification types may include:

- check-in reminder;
- overdue quest;
- quest due today;
- stale lead;
- lead next action due;
- weekly review reminder.

This phase is external notification delivery.

The in-app follow-up command center remains Phase 6.3.

## Phase 7.4 — Outreach Templates and Follow-up Automation

Planned deterministic features:

- reusable templates;
- first contact;
- follow-up;
- proposal follow-up;
- no-response follow-up;
- template variables;
- copy-to-clipboard;
- outreach-sent timestamp;
- automatic next-follow-up date;
- follow-up history.

The first version must not automatically send messages.

## Phase 7.5 — Insights and Trend Dashboard

Use Chart.js first.

Personal insights:

- energy trend;
- energy versus output;
- free hours versus completed quests;
- check-in completion;
- cash-in versus expenses;
- cash trajectory.

CRM insights:

- leads found per week;
- contacted leads;
- follow-ups completed;
- stale leads;
- conversion rate;
- lead source;
- pipeline distribution;
- average time in stage.

Director diagnostics:

- signal frequency;
- recommendation acceptance;
- recommendation outcomes;
- priority-score distribution.

## Phase 7.6 — Mobile-Friendly PWA

Planned:

- manifest;
- icons;
- standalone installation;
- service worker;
- offline shell;
- offline check-in draft;
- retry on restored connectivity;
- mobile interaction improvements.

Do not broadly cache authenticated personal HTML.

## Phase 7.7 — Data Export and Portability

Planned formats:

```text
JSON
CSV per table
ZIP package
```

Every export must be user-scoped.

Member exports contain only that Member's data.

Lead Researcher exports contain only authorized CRM data.

Passwords, password hashes, session secrets, and environment secrets must never
be exported.

---

# Phase 8 — Budget-Safe AI Continuation

**Status:** Planned  
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
Phase 6.1 — Staff Workflow, Research Ownership, and Approval
```

Recommended branch:

```bash
cd /Users/johnionmiranda/Documents/projects/mark-os

git switch main
git pull --ff-only origin main
git status

git switch -c feature/lead-research-review-workflow
```

Before coding, inspect:

```text
app/db/leads.py
app/services/leads.py
app/services/access_control.py
app/routes/client_hunting.py
app/templates/client_hunting.html
app/templates/lead_detail.html
app/templates/edit_lead.html
app/services/team_users.py
tests/test_leads.py
tests/test_lead_ownership.py
tests/test_role_permissions.py
tests/test_application.py
```

### First Phase 6.1 implementation order

```text
6.1A  Additive research/review schema
6.1B  Backfill existing leads
6.1C  Service-level permission policy
6.1D  Brother research-edit workflow
6.1E  Mark review and approval workflow
6.1F  Owner-only major stage transitions
6.1G  Templates and CRM queues
6.1H  Migration, permission, and route tests
6.1I  Full-suite and browser verification
```

Do not implement the full activity timeline in 6.1.

The activity timeline is Phase 6.2.

---

# 16. MoSCoW Priorities

## Must have now

- separate Owner and brother accounts;
- brother CRM-only access;
- research editing;
- lead assignment;
- research author;
- review author;
- review date;
- approval status;
- Owner-only major transitions;
- no private finance access for brother;
- service-level permission tests;
- lead activity timeline;
- follow-up command center;
- CSV preview and export.

## Should have after the core staff flow

- bulk assignment;
- approved-leads export;
- deterministic outreach templates;
- CRM backup download;
- discovery qualification after replies;
- proposal tracking after proposals begin.

## Could have later

- external notifications;
- PWA;
- advanced dashboards;
- full data portability;
- embeddings;
- Neo4j;
- LangGraph;
- Gmail and Calendar observation.

## Will not have yet

- unrestricted autonomous agents;
- automatic external outreach;
- full proposal document generation;
- complex invoicing before Client #1;
- AI as the database;
- AI-generated raw SQL;
- automatic storage of every conversation.

---

# 17. Safety Rules

1. Database records are the source of truth.
2. AI never receives unrestricted database access.
3. Role restrictions are enforced server-side.
4. Family data is private by default.
5. Brother cannot access private finance.
6. Brother cannot approve outreach or mark Won/Lost.
7. Major status and pricing decisions belong to Mark.
8. Ordinary deletion is soft deletion.
9. Permanent purge is not a normal UI action.
10. Quest XP is immutable and awarded once.
11. Secrets are never stored in memory or exports.
12. External actions require confirmation.
13. Migrations preserve existing production data.
14. Backups are required before deployment and schema changes.
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
| Phase 6.1 | Next | Staff research and approval workflow |
| Phase 6.2 | Planned | Lead activity timeline |
| Phase 6.3 | Planned | Follow-up command center |
| Phase 6.4 | Planned | Bulk lead management |
| Phase 6.5 | Trigger-based | Build after replies |
| Phase 6.6 | Trigger-based | Build at proposal stage |
| Phase 6.7 | Trigger-based | Build after Client #1 |
| Phase 6.8 | Trigger-based | Build during delivery and billing |
| Phase 7 | Parked | Product hardening and growth |
| Phase 8 | Planned | Budget-safe AI continuation |

---

# 19. Decision Log

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
Phase 6 = Agency CRM Operations
Phase 7 = Product Hardening & Growth
Phase 8 = Budget-Safe AI Continuation
```

Reason:

- keep numbering chronological;
- avoid returning to an old Phase 5.3 label;
- preserve completed Phase 5 history;
- separate operational agency work from optional AI work.

## 2026-08-05 — Park backup work

Decision:

- keep completed local Phase 7.1 backup code for reuse;
- do not discard it;
- resume it after critical agency workflow work, unless production risk requires
  earlier completion.

Reason:

- backup is still high priority;
- staff workflow is the immediate usability blocker;
- both bodies of work remain independent.

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
