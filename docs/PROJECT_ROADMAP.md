# MARK-OS Project Roadmap

**Last updated:** 2026-08-04  
**Current active phase:** Phase 6 — Product Hardening & Growth  
**Next implementation:** Phase 6.1 — Backup & Disaster Recovery

---

## Purpose

This document is the main roadmap for MARK-OS.

Use it to remember:

- what has already been completed;
- what phase is currently active;
- what should be built next;
- which work has been postponed;
- how old phase numbers were renumbered.

Update this file whenever a phase or subphase is completed.

---

## Numbering Decision

MARK-OS already completed the foundation of Phase 5 before Product Hardening
was proposed.

To avoid confusing backward jumps:

- **Phase 5 remains the completed AI foundation phase.**
- **Phase 6 becomes Product Hardening & Growth and is the current phase.**
- **The old Phase 5.3 and later AI work moves to Phase 7.**
- No completed phase numbers will be reused.

### Renumbering rule

| Old number | New number |
|---|---|
| Phase 5.1 | Phase 5.1 — unchanged |
| Phase 5.2 | Phase 5.2 — unchanged |
| Phase 5.3 | Phase 7.1 |
| Phase 5.4 | Phase 7.2 |
| Phase 5.5 | Phase 7.3 |
| Phase 5.6 | Phase 7.4 |
| Later Phase 5 items | Continue sequentially under Phase 7 |

The detailed AI scope should continue to follow `docs/AI_ARCHITECTURE_V2.md`.
Only the future numbering changes.

---

# Current Project Status

## Phases 1–4 — Core MARK-OS Foundation

**Status:** Completed

Main outcomes include:

- FastAPI, HTMX, Bulma, and SQLite application foundation;
- authentication and database login;
- goals, projects, quests, history, daily check-ins, and XP;
- client-hunting CRM;
- Railway deployment foundation;
- family multi-user workspaces;
- frontend theme and sidebar navigation.

---

## Phase 5 — AI Foundation

**Status:** Paused after Phase 5.2  
**Reason:** Product hardening and business-growth features have higher
immediate value and do not require AI spending.

Completed work includes the existing chat and AI architecture foundation.

Do not continue the old Phase 5.3 numbering. The remaining AI work resumes
under Phase 7.

---

# Phase 6 — Product Hardening & Growth

**Status:** Current phase

Phase 6 does not require paid AI model calls and should not affect the
PHP 200 monthly AI budget.

The build order below is the official sequence.

---

## Phase 6.1 — Backup & Disaster Recovery

**Priority:** Critical  
**Status:** Next

### Goal

Protect the MARK-OS database and CRM pipeline from accidental deletion,
corruption, failed deployment, or Railway volume loss.

### Deliverables

- manual backup command;
- timestamped SQLite backup files;
- scheduled automated backups;
- backup storage outside the Railway application volume;
- backup retention policy;
- SQLite integrity verification;
- documented restore command;
- restore test using a temporary database;
- backup and restore logs.

### Definition of done

Phase 6.1 is complete only when:

- a backup is created successfully;
- the backup passes an integrity check;
- the backup is restored into a temporary location;
- the restored application data can be read;
- the restore procedure is documented and tested.

### Recommended branch

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/backup-disaster-recovery
```

---

## Phase 6.2 — Security & Audit Foundation

**Priority:** High

### Goal

Protect the M10 multi-user system and make sensitive administrative actions
traceable.

### Deliverables

- login rate limiting;
- session tracking;
- session revocation;
- logout from all devices;
- session invalidation after password reset;
- admin audit-log table;
- role-change audit events;
- account activation and deactivation events;
- member creation and removal events;
- failed-login events;
- audit-log viewer for the owner;
- authorization and IDOR regression tests;
- secure-cookie and session-expiry review;
- CSRF review;
- sensitive-log review.

### Definition of done

- repeated login abuse is limited;
- the owner can revoke active sessions;
- sensitive account changes appear in the audit log;
- members cannot access another user's private records;
- lead sourcers remain CRM-only;
- security regression tests pass.

---

## Phase 6.3 — Notifications & Nudges

**Priority:** High

### Goal

Remind users about important work without requiring AI.

### Initial notifications

- daily check-in reminder;
- overdue quest alert;
- quest due today;
- stale lead with no contact for five days;
- lead next action due today;
- weekly review reminder.

### Architecture

```text
Scheduled runner
    ↓
Notification rules
    ↓
Notification queue
    ↓
Delivery adapter
    ├── Email
    ├── Telegram
    └── Discord webhook
```

### Requirements

- notification preferences per user;
- delivery-channel configuration;
- sent, failed, and skipped status;
- retry limit;
- duplicate prevention;
- notification history.

### Suggested deduplication key

```text
user_id + notification_type + resource_id + notification_date
```

### Definition of done

- at least one delivery channel works;
- reminders are generated from database rules;
- the same reminder is not sent repeatedly;
- failures are logged without crashing the app.

---

## Phase 6.4 — Outreach Templates & Follow-up Automation

**Priority:** High  
**Business purpose:** Directly support the USD 10,000-per-month goal.

### Goal

Help the owner and lead sourcers perform consistent outreach without waiting
for the AI router.

### Deliverables

- reusable outreach templates;
- first-contact templates;
- follow-up templates;
- proposal follow-up templates;
- no-response follow-up templates;
- template categories;
- template variables;
- copy-to-clipboard action;
- outreach-sent timestamp;
- next-follow-up date;
- overdue-follow-up queue;
- mark-follow-up-complete action;
- follow-up history per lead.

### Initial template variables

```text
{{ contact_person }}
{{ company }}
{{ job_title }}
{{ problem_opportunity }}
{{ why_mark_fits }}
{{ source }}
```

### Important limitation

The first version should prepare and track messages but should not
automatically send messages to leads.

### Definition of done

- a template can be selected for a lead;
- variables are filled deterministically;
- the message can be copied;
- outreach activity is recorded;
- the next follow-up date is calculated;
- overdue follow-ups appear in one queue.

---

## Phase 6.5 — Insights & Trend Dashboard

**Priority:** Medium to high

### Goal

Turn existing MARK-OS data into useful, zero-AI business and personal
insights.

### Technology

Use **Chart.js** for the first version.

Do not use D3.js unless MARK-OS later needs highly customized visualizations.

### Personal insights

- energy trend;
- energy versus completed work;
- free hours versus completed quests;
- check-in completion rate;
- weekly quest completion;
- cash-in versus expenses;
- cash trajectory.

### Client-hunting insights

- leads found per week;
- leads contacted per week;
- follow-ups completed;
- stale leads;
- lead conversion rate;
- leads by source;
- leads by pipeline stage;
- average days in each stage.

### Director diagnostics

- most frequently triggered Director signal;
- recommendation frequency;
- recommendations accepted;
- recommendations ignored;
- quest-priority score distribution;
- outcomes by recommendation type.

### Definition of done

- dashboard queries are user-scoped;
- CRM metrics respect role permissions;
- charts work without AI calls;
- empty datasets render safely;
- calculations have tests.

---

## Phase 6.6 — Mobile-Friendly PWA

**Priority:** Medium

### Goal

Make MARK-OS installable and convenient for daily mobile use.

### Deliverables

- web app manifest;
- application icons;
- installable standalone mode;
- service worker;
- offline application shell;
- offline daily-check-in draft;
- retry submission when connectivity returns;
- touch-friendly controls;
- mobile sidebar improvements.

### Security rule

Do not broadly cache authenticated HTML pages containing private user data.

Cache only:

- safe static assets;
- application shell resources;
- explicitly controlled offline drafts.

### Definition of done

- MARK-OS can be installed on a supported phone;
- the main shell loads reliably;
- a check-in draft can survive temporary disconnection;
- private pages are not exposed through unsafe caching.

---

## Phase 6.7 — Data Export & Portability

**Priority:** Medium

### Goal

Allow every user to download the data they are authorized to own or manage.

### Export formats

- JSON for complete structured exports;
- CSV files per table;
- ZIP package containing all export files.

### Owner exports

- own personal data;
- authorized CRM data;
- administrative audit information;
- family-account metadata where appropriate.

### Family-member exports

- own profile;
- own goals;
- own projects;
- own quests;
- own check-ins;
- own history;
- own chat sessions;
- own memories.

### Lead-sourcer exports

Only CRM information the lead sourcer is authorized to access.

### Definition of done

- exports are user-scoped;
- one member cannot export another member's data;
- generated files contain no passwords or secrets;
- large exports fail safely;
- export actions are audited.

---

# Phase 7 — Budget-Safe AI Continuation

**Status:** Planned after Phase 6

Phase 7 contains the work that was previously called Phase 5.3 and later.

The detailed implementation should follow `docs/AI_ARCHITECTURE_V2.md`.

## Planned direction

- structured memory and embeddings;
- budget-safe AI routing;
- controlled AI tools;
- per-user AI permissions;
- Director recommendations;
- weekly review agent;
- model usage and cost controls;
- AI production hardening.

## Budget rule

```text
Maximum target: PHP 200 per month
```

## Data rule

Embed only useful long-term information, such as:

- summarized important memories;
- completed quest outcomes;
- important decisions;
- long-term preferences;
- weekly summaries.

Do not embed:

- greetings;
- every short chat reply;
- temporary errors;
- repeated messages;
- complete raw conversations by default.

---

# Official Execution Order

```text
Phase 6.1  Backup & Disaster Recovery
Phase 6.2  Security & Audit Foundation
Phase 6.3  Notifications & Nudges
Phase 6.4  Outreach Templates & Follow-up Automation
Phase 6.5  Insights & Trend Dashboard
Phase 6.6  Mobile-Friendly PWA
Phase 6.7  Data Export & Portability
Phase 7    Resume Budget-Safe AI development
```

---

# Development Rules

For every subphase:

1. Start from an updated `main` branch.
2. Create a dedicated feature branch.
3. Back up the database before schema changes.
4. Add migration code that is safe to run repeatedly.
5. Add tests for permissions and user ownership.
6. Run targeted tests.
7. Run the complete test suite.
8. Perform a local browser smoke test.
9. Review `git status` before staging.
10. Do not commit `.env`, SQLite databases, backups, or temporary fix scripts.
11. Merge to `main` only after all tests pass.
12. Update this roadmap after completion.

---

# Current Next Action

Begin **Phase 6.1 — Backup & Disaster Recovery**.

```bash
cd /Users/johnionmiranda/Documents/projects/mark-os

git switch main
git pull --ff-only origin main
git status

git switch -c feature/backup-disaster-recovery
```

Before writing production code, define:

- current Railway SQLite database path;
- backup destination;
- external storage provider;
- backup frequency;
- retention period;
- restore-test procedure.

---

# Phase Completion Log

| Phase | Status | Completion date | Commit |
|---|---|---|---|
| Phases 1–4 | Completed | — | — |
| Phase 5.1–5.2 | Completed | — | — |
| Phase 6.1 | Not started | — | — |
| Phase 6.2 | Not started | — | — |
| Phase 6.3 | Not started | — | — |
| Phase 6.4 | Not started | — | — |
| Phase 6.5 | Not started | — | — |
| Phase 6.6 | Not started | — | — |
| Phase 6.7 | Not started | — | — |
| Phase 7 | Planned | — | — |

---

# Decision Log

## 2026-08-04

Decision:

- pause AI work after Phase 5.2;
- complete Product Hardening & Growth first;
- keep Product Hardening as Phase 6;
- move the old Phase 5.3+ work to Phase 7;
- start Phase 6 with backup and disaster recovery.

Reason:

- protect the only production database volume;
- reduce risk before adding more features;
- deliver business value without AI spending;
- keep project numbering chronological and easier to follow.
