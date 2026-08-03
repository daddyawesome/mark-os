# MARK-OS Complete Project Handoff

**Project:** MARK-OS  
**Repository:** `github.com/daddyawesome/mark-os`  
**Current date:** 2026-08-03  
**Current development stage:** Phase 5 preparation / Memory Loop  
**Primary owner:** Mark  
**Deployment:** Railway  
**Current operational database:** SQLite with a persistent Railway volume  
**Planned graph-memory database:** Neo4j AuraDB Free  
**Planned semantic memory:** SQLite + `sqlite-vec`, with a future PostgreSQL + `pgvector` path

---

## 1. Executive Summary

MARK-OS is a personal operating system and second brain.

It is not only an AI chat page. Its actual product definition is:

```text
AI + database + memory + quests + review + budget + safety
```

The intended experience is Jarvis-like, but controlled and affordable:

- remember conversations, decisions, lessons, quests, and outcomes;
- create, read, update, and complete quests through chat;
- track progress, time, evidence, XP, and levels;
- understand connections among people, goals, projects, problems, and solutions;
- retrieve relevant history instead of sending the whole database to an AI model;
- recommend the next useful action;
- observe approved Gmail and Calendar information later;
- remain useful even when the AI provider is unavailable or the monthly budget is exhausted.

MARK-OS must never depend on an AI model as its source of truth.

```text
Database = truth
Python services = rules and validation
Vector search = semantic recall
Graph database = relationship recall
LangGraph = controlled workflow
LLM = reasoning and communication
```

---

## 2. User and Product Goals

### Primary long-term goal

Build a personal and business operating system that helps Mark:

- grow toward at least USD 10,000 per month;
- organize work, family, health, learning, finances, and projects;
- overcome the recurring blocker of finding qualified clients;
- turn completed work into reusable knowledge;
- build products and eventually support a team.

### Available skills to use in the system

- Python
- SQL
- Power BI
- Azure
- data engineering
- automation
- FastAPI
- HTMX
- SQLite
- basic web development

### Constraints

- Keep AI spending at or below approximately **PHP 200 per month**.
- Prefer deterministic Python operations over paid AI calls.
- Preserve weekends for family where possible.
- Keep the system usable on modest hardware and Railway.
- Do not store passwords, API keys, banking credentials, or unnecessary confidential work data in memory.
- Require approval for sensitive actions.

---

## 3. Current Technology Stack

### Implemented

| Layer | Current choice |
|---|---|
| Backend | FastAPI |
| UI | HTMX + Bulma |
| Operational database | SQLite |
| Deployment | Railway |
| Persistent storage | Railway volume |
| Authentication | Existing login system |
| Source control | GitHub |
| Local development | macOS and Windows |
| Python environment | `.venv` |

### Planned for Phase 5

| Layer | Planned choice |
|---|---|
| Agent workflow | LangGraph |
| Semantic vectors | `sqlite-vec` initially |
| Embedding provider | Environment-configured; do not hardcode until price and availability are verified |
| Graph memory | Neo4j AuraDB Free |
| AI provider | Provider abstraction; model names supplied through environment variables |
| Future operational upgrade | PostgreSQL |
| Future vector upgrade | PostgreSQL + `pgvector` |

### Important architecture decision

**Do not replace SQLite with Neo4j.**

SQLite remains the source of truth for:

- chat history;
- quests and quest updates;
- goals and projects;
- XP and levels;
- check-ins;
- budgets;
- AI usage;
- audit logs.

Neo4j is an additional relationship-memory layer for questions such as:

- Which quests support this goal?
- Which repeated blockers affect several projects?
- What solution fixed a similar problem before?
- Which completed business experiments produced positive outcomes?

If Neo4j is unavailable, MARK-OS must continue working with SQLite and vector memory.

---

## 4. Current Known Repository Structure

The exact repository tree must be inspected before changes. Known files and paths include:

```text
mark-os/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── services/
│   ├── templates/
│   └── ...
├── data/
│   └── mark_os.db
├── docs/
├── .venv/
└── ...
```

Known local macOS path:

```text
/Users/johnionmiranda/Documents/projects/mark-os
```

Known Windows path used previously:

```text
C:\Users\rmira\OneDrive\Documents\Projects\mark-os-v0.1
```

Codex must inspect the real tree and existing conventions rather than assume missing files.

---

## 5. Existing Database

The current application initializes SQLite through:

```python
DB_PATH = Path(
    os.getenv(
        "MARK_OS_DB_PATH",
        str(DATA_DIR / "mark_os.db"),
    )
)
```

The current database file is normally:

```text
data/mark_os.db
```

Railway should point `MARK_OS_DB_PATH` to the mounted persistent volume when configured.

### Existing tables

The current `database.py` includes:

```text
profile
goals
projects
checkins
directions
game_state
game_history
memories
timeline_events
system_meta
tasks
quest_updates
xp_ledger
```

### Existing table responsibilities

#### `profile`

Stores the single-user profile, including:

- name;
- wealth goal;
- weekday hours;
- weekend rule;
- strongest skills;
- primary blocker.

#### `goals`

Stores long-term goals with:

- title;
- category;
- status;
- priority;
- created timestamp.

#### `projects`

Stores projects with:

- purpose;
- status;
- priority;
- progress;
- next action;
- optional goal connection;
- timestamps.

#### `checkins`

Stores daily check-ins, including:

- check-in date;
- legacy cash field;
- `cash_in`;
- expenses;
- free hours;
- energy;
- accomplishment;
- blocker;
- notes;
- timestamps.

Business rule:

```text
cash_in adds to available cash
expenses subtract from available cash
```

#### `directions`

Stores generated daily direction associated with a check-in:

- main quest;
- reason;
- side quests;
- what to avoid;
- success signal.

#### `game_state`

Stores current:

- level;
- total XP;
- XP into the current level;
- class;
- threshold mode;
- source;
- notes.

#### `game_history`

Stores level and game events.

#### `memories`

Current memory structure includes:

- `memory_type`;
- unique `memory_key`;
- `memory_value`;
- importance;
- source;
- active flag;
- timestamps.

Phase 5 should **migrate this table additively**. Do not drop or replace it.

#### `timeline_events`

Stores important dated events and JSON details.

#### `tasks`

This is the current Quest Engine table. It includes:

- optional project and goal links;
- title and description;
- status;
- priority;
- estimated and actual time;
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
- started/completed/created/updated timestamps.

#### `quest_updates`

Stores progress history, notes, time, blockers, and event type.

#### `xp_ledger`

Stores immutable XP events and protects quest-completion XP from being awarded twice.

### Database safety rule

For older SQLite databases:

```text
create base tables
→ inspect existing columns
→ add missing columns
→ backfill values
→ create indexes that depend on migrated columns
```

Never place an index for a newly migrated column in the initial `executescript()` block.

---

## 6. Work Completed So Far

### Foundation completed

- FastAPI application foundation.
- HTMX/Bulma UI foundation.
- Local SQLite database.
- Railway deployment.
- Persistent Railway volume.
- Login works locally.
- Theme corrections completed.
- Health endpoint used for Railway deployment checks.

### Phase 4 Quest Engine completed or substantially implemented

- Create quests.
- Open quests.
- Start quests.
- Block quests.
- Update progress.
- Save notes.
- Save actual and session minutes.
- Complete quests.
- Require completion results.
- Store evidence.
- Create timeline events.
- Award XP exactly once.
- Preserve Level 3/imported level state.
- Record level-up history.
- Prevent duplicate XP through the ledger.

### Check-in improvements completed

- Added `cash_in`.
- Kept expenses as a subtraction.
- Added `updated_at` safely for older SQLite databases.
- Requested edit/delete support for mistaken or duplicate history records.

### Migration fixes completed locally

The following startup problems were repaired:

1. `event_key` index was created before the column existed.
2. `updated_at` attempted a non-constant `CURRENT_TIMESTAMP` default during `ALTER TABLE`.
3. `idx_tasks_goal` was created before the legacy `tasks` table received `goal_id`.
4. Ordinary indexes were moved after legacy-schema migrations for safer startup.

Current local result:

```text
The app starts without the goal_id migration error.
```

Deployment status still needs verification:

- confirm the corrected `app/database.py` was committed;
- confirm it was merged into `main`;
- confirm Railway deployed the latest `main`;
- confirm the production database starts and existing data remains.

### Git branches already created

```text
feature/memory-loop
feature/quest-engine
feature/budget-safe
feature/ai-director
```

These branches were initially created from the same point. Work must happen one branch at a time.

---

## 7. Current Project Position

```text
Phase 4: Quest Engine foundation — completed/stabilizing
Phase 5 architecture — decided
Phase 5 feature implementation — not yet started
Immediate work — verify deployment, then implement Step 5.1
```

The current coding branch should be:

```bash
git checkout feature/memory-loop
```

Before Phase 5 code, verify that `main` contains the migration repair.

---

## 8. Product Loops

MARK-OS will become agentic through controlled loops rather than many uncontrolled agents.

### Required loops

1. Daily Check-in Loop
2. Quest Progress Loop
3. XP/Level Loop
4. Budget-Safe Chat Loop
5. Memory Extraction Loop
6. Weekly Review Loop
7. Calendar/Gmail Observation Loop
8. AI Director Loop
9. Learning Loop

### Every loop must define

1. clear goal;
2. allowed input;
3. approved tools;
4. maximum steps;
5. stop condition;
6. safety rule;
7. memory output;
8. audit record.

### Example loop contract

```text
Loop: Memory Extraction

Goal:
Save one useful reusable lesson.

Input:
A completed interaction, important decision, or quest outcome.

Maximum steps:
3

Maximum AI calls:
1 extraction call, unless explicitly retried.

Stop conditions:
- memory saved;
- duplicate found;
- content judged unimportant;
- safety filter rejects it;
- one extraction attempt fails.

Safety rule:
Never automatically store credentials or sensitive data.

Memory output:
One summarized memory, optional vector embedding, and optional graph relationships.

Audit:
Record the source, extraction reason, result, and model usage.
```

---

## 9. Agent Architecture

### Phase 5 agent count

Start with:

```text
1 Director Agent
```

Do not create eight separate agents.

The eight loops become nodes or deterministic service calls inside one controlled workflow.

### Planned LangGraph workflow

```text
User message
    ↓
Save message
    ↓
Rule-based intent check
    ↓
Budget guard
    ↓
Load recent chat
    ↓
Load exact quest/project data
    ↓
Retrieve semantic memories
    ↓
Retrieve graph relationships when available
    ↓
LLM selects approved action/tool
    ↓
Python validates request
    ↓
Execute service function
    ↓
Verify database result
    ↓
Optional memory extraction
    ↓
Save assistant response and agent audit
    ↓
Stop
```

### Important distinction

```text
LangGraph graph = workflow and execution path
Neo4j graph = knowledge and relationships
RAG = retrieval technique
```

LangGraph does not replace RAG.

---

## 10. Hybrid Memory Architecture

MARK-OS will use three complementary memory layers.

### 10.1 Relational memory

SQLite stores exact records:

- complete chat history;
- current and completed quests;
- XP events;
- check-ins;
- budgets;
- agent runs;
- structured memories.

### 10.2 Vector memory

Vector search finds similar meaning even when wording differs.

Example:

```text
Question:
Why did the scheduled Power BI refresh fail?

Possible retrieved memory:
The Power BI gateway used different credentials from Desktop, causing scheduled refresh failure.
```

Store embeddings only for useful summarized knowledge:

- decisions;
- technical solutions;
- business results;
- quest outcomes;
- stable preferences;
- important milestones.

Do not embed:

- greetings;
- acknowledgements;
- every short response;
- duplicates;
- secrets;
- temporary chat noise.

### 10.3 Graph memory

Neo4j stores connected entities.

Initial node types:

```text
Person
Goal
Project
Quest
Skill
Decision
Problem
Solution
BusinessExperiment
Outcome
Memory
```

Initial relationship types:

```text
WORKS_ON
SUPPORTS
DEPENDS_ON
BLOCKED_BY
SOLVED_BY
LEARNED_FROM
RELATED_TO
CREATED_FROM
COMPLETED_AS_PART_OF
PREFERS
HAS_PHASE
```

Example:

```text
(Mark)-[:WORKS_ON]->(MARK_OS)
(MARK_OS)-[:HAS_PHASE]->(Phase_5)
(Phase_5)-[:DEPENDS_ON]->(Memory_Loop)
(Database_Startup_Error)-[:SOLVED_BY]->(Migration_Index_Order_Fix)
(Client_Outreach_Quest)-[:SUPPORTS]->(USD_10000_Monthly_Goal)
```

### Graph safety

- Graph writes originate from approved structured records.
- Do not extract graph triples from every message initially.
- Python validates allowed entity and relationship types.
- Store source IDs and confidence.
- If Neo4j is unavailable, continue without graph context.
- Never make Neo4j the only copy of critical quest, XP, or financial data.

---

## 11. Phase 5 Build Plan

### Step 5.0 — Stabilize and verify Phase 4

Acceptance criteria:

- local startup succeeds;
- `main` contains the migration repair;
- Railway latest deployment succeeds;
- existing quests, XP, check-ins, and memory remain;
- `/health` succeeds.

### Step 5.1 — Persistent chat

Add tables:

```text
chat_sessions
chat_messages
```

Required service functions:

```text
create_chat_session
get_chat_session
list_chat_sessions
rename_chat_session
delete_chat_session
save_chat_message
edit_chat_message
delete_chat_message
get_recent_chat_messages
```

Requirements:

- save user and assistant messages;
- load only the last 8–10 messages for normal chat;
- preserve complete history in SQLite;
- prevent duplicate submissions;
- support history edit/delete with confirmation;
- use foreign keys and safe indexes.

### Step 5.2 — Agent audit

Add:

```text
agent_runs
agent_steps
```

Track:

- session;
- user message;
- intent;
- status;
- loop selected;
- step count;
- AI calls;
- tool calls;
- model/provider;
- token/cost estimates;
- errors;
- timestamps.

### Step 5.3 — Structured long-term memory

Migrate the existing `memories` table additively.

Suggested additional fields:

```text
source_type
source_id
confidence
last_used_at
embedding_model
embedding_dimension
embedding_status
sensitivity
version
superseded_by
```

Do not rename or delete existing fields until a tested compatibility migration exists.

### Step 5.4 — Memory extraction loop

Process only important chats, decisions, and outcomes.

Flow:

```text
candidate information
→ importance/safety check
→ compact summary
→ duplicate check
→ store memory
→ queue optional embedding
→ queue optional graph relationships
→ stop
```

### Step 5.5 — Semantic vector retrieval

Initial implementation:

```text
SQLite + sqlite-vec
```

Requirements:

- provider interface for embeddings;
- model name from environment;
- initial target dimension configurable, such as 768;
- top 5–8 results;
- similarity threshold;
- importance and active filters;
- no full-chat embedding;
- embedding failures must not block normal chat.

### Step 5.6 — Quest tools in chat

Approved tools:

```text
create_quest
list_quests
get_quest
update_quest
complete_quest
add_quest_note
search_completed_quests
```

Rules:

- AI never receives unrestricted SQL;
- Python validates all arguments;
- completion requires a result;
- XP remains immutable and awarded once;
- deletion requires confirmation;
- quest outcome may create a memory.

### Step 5.7 — Budget-safe AI router

Add:

```text
ai_usage_ledger
budget_settings
```

Required protections:

```python
MONTHLY_AI_BUDGET_PHP = 200.00
WARNING_THRESHOLD_PHP = 150.00
MAX_AI_CALLS_PER_MESSAGE = 2
MAX_LOOP_STEPS = 3
MAX_RECENT_MESSAGES = 10
MAX_VECTOR_MEMORIES = 8
MAX_GRAPH_HOPS = 2
MAX_GRAPH_ENTITIES = 20
```

Rules:

- Python handles simple exact operations.
- Use a small/cheap model for normal routing and chat.
- Use a stronger model only for high-value complexity and within budget.
- Model and embedding names come from environment variables.
- At the warning threshold, disable automatic strong-model routing.
- At the hard limit, database-only features continue working.
- Do not rely on any old model name or price without current verification.

### Step 5.8 — Neo4j graph connection

Use Neo4j AuraDB Free initially.

Add a service such as:

```text
app/services/graph_database.py
```

Environment variables:

```text
NEO4J_URI
NEO4J_USERNAME
NEO4J_PASSWORD
NEO4J_DATABASE
```

Requirements:

- connection test;
- timeout and graceful fallback;
- controlled upsert;
- source and confidence metadata;
- 1–2 hop retrieval;
- no critical operational data stored only in Neo4j.

### Step 5.9 — Hybrid retriever

Combine:

```text
recent chat
+ exact SQLite quest/project records
+ top semantic memories
+ small Neo4j subgraph
```

Create a compact context summary before the main AI call.

### Step 5.10 — LangGraph Director

Only after the services above are independently tested.

Director responsibilities:

- select the correct loop;
- call approved tools;
- respect budget and safety;
- stop after bounded work;
- log every run.

### Step 5.11 — Weekly Review Loop

Read:

- completed and overdue quests;
- time spent;
- XP and levels;
- check-ins;
- cash-in and expenses;
- important memories;
- repeated graph blockers.

Produce:

- accomplishments;
- missed commitments;
- lessons;
- financial summary;
- risks;
- top priorities;
- suggested quests requiring approval.

### Step 5.12 — Gmail and Calendar observation

Later phase.

Initial behavior:

- read approved data;
- identify commitments and deadlines;
- suggest quests;
- do not automatically send email;
- do not automatically accept, modify, or delete calendar events.

---

## 12. MoSCoW Priorities

### Must have

- persistent chat sessions and messages;
- recent-chat retrieval;
- quest create/read/update/complete tools;
- completed-quest lookup;
- structured memory;
- semantic retrieval;
- intent classification;
- controlled Python tools;
- XP awarded once;
- API usage and budget tracking;
- agent-run logging;
- duplicate protection;
- edit/delete confirmation;
- safe migration support;
- graceful failure when AI, embeddings, or Neo4j are unavailable.

### Should have

- memory extraction loop;
- quest outcome memories;
- user-visible chat history;
- model routing;
- weekly review;
- life-area classification;
- graph entities and relationships;
- hybrid vector + graph retrieval;
- cost display;
- memory confidence and source metadata.

### Could have later

- local Ollama model;
- voice input/output;
- graph visualization;
- automatic conversation summaries;
- memory confidence decay/reinforcement;
- multiple AI providers;
- file/codebase retrieval;
- notifications;
- family profiles;
- proactive observations.

### Won't have yet

- unrestricted terminal access;
- unrestricted SQL execution;
- autonomous email sending;
- automatic purchases;
- continuous screen recording;
- custom model training;
- multiple agents debating every request;
- endless self-improvement loops;
- automatic Git commits/deployments without approval;
- embedding every chat message;
- replacing SQLite with Neo4j.

---

## 13. Safety Rules

The AI may automatically:

- read approved quests and memories;
- create a normal quest when explicitly instructed;
- update non-sensitive quest progress;
- add notes;
- retrieve relevant context;
- save a non-sensitive approved lesson;
- generate suggestions.

The AI must request approval before:

- deleting quests, messages, or memories;
- changing earned XP;
- spending money;
- sending email;
- changing calendar events;
- executing terminal commands;
- changing production data;
- committing or deploying code;
- storing sensitive personal information.

Never store:

- passwords;
- API keys;
- tokens;
- bank credentials;
- private keys;
- unnecessary confidential employer data.

---

## 14. Definition of Phase 5 Success

A user can type:

```text
Create a quest to contact one qualified Power BI client tomorrow.
```

MARK-OS should:

1. save the user message;
2. classify the intent;
3. create the quest through an approved Python service;
4. return the created quest;
5. save the assistant response;
6. record the agent run.

Later, the user can type:

```text
I contacted the client, sent my portfolio, and spent 35 minutes.
```

MARK-OS should:

1. retrieve the matching active quest;
2. add the result and time;
3. complete the quest;
4. award XP exactly once;
5. save a quest update and timeline event;
6. create an important outcome memory;
7. optionally create vector and graph records;
8. use the lesson in future business guidance.

---

## 15. Git Workflow

### Check current state

```bash
cd /Users/johnionmiranda/Documents/projects/mark-os
git fetch origin
git status
git branch --show-current
git remote -v
```

### Verify local and GitHub synchronization

```bash
git log origin/main..HEAD --oneline
git log HEAD..origin/main --oneline
```

- First command shows local commits not on GitHub.
- Second command shows GitHub commits missing locally.

### Normal feature workflow

```bash
git checkout main
git pull --ff-only origin main
git checkout feature/memory-loop
git merge main
```

After tested work:

```bash
git add <specific-files>
git commit -m "Add persistent chat foundation"
git push -u origin feature/memory-loop
```

After review:

```bash
git checkout main
git pull --ff-only origin main
git merge --no-ff feature/memory-loop
git push origin main
```

### Important Git rules

- Do not commit `.venv`.
- Do not commit `data/mark_os.db`.
- Do not commit `.env`.
- Do not commit Neo4j credentials or AI keys.
- Do not use `git add .` without reviewing `git status`.
- Make a database backup before migrations.
- Keep migration fixes in separate commits from new Phase 5 features.

---

## 16. Railway Deployment

Railway should deploy the branch configured in the service settings, normally `main`.

After pushing `main`:

1. open the MARK-OS Railway project;
2. open the web service;
3. check the connected repository and branch;
4. open the newest deployment;
5. inspect build and runtime logs;
6. verify no SQLite migration errors;
7. open `/health`;
8. test login, quests, XP, check-ins, and existing data.

Never delete or recreate the Railway volume to fix a migration error.

---

## 17. Getting the Project from GitHub

### Option A — Existing local repository with no important uncommitted work

```bash
cd /Users/johnionmiranda/Documents/projects/mark-os
git status
git fetch --all --prune
git checkout main
git pull --ff-only origin main
```

Then prepare the Phase 5 branch:

```bash
git checkout feature/memory-loop
git merge main
git status
```

### Option B — Existing repository with uncommitted work

First save the work:

```bash
cd /Users/johnionmiranda/Documents/projects/mark-os
git status
git stash push -u -m "backup before GitHub sync"
git fetch --all --prune
git checkout main
git pull --ff-only origin main
```

Restore only after checking:

```bash
git stash list
git stash show -p stash@{0}
git stash pop
```

Resolve conflicts carefully.

### Option C — Fresh clone

Do not delete the old folder. Rename it first:

```bash
cd /Users/johnionmiranda/Documents/projects
mv mark-os "mark-os-backup-$(date +%Y%m%d-%H%M%S)"
git clone https://github.com/daddyawesome/mark-os.git
cd mark-os
git fetch --all --prune
git checkout main
git pull --ff-only origin main
```

List branches:

```bash
git branch -a
```

Checkout Phase 5:

```bash
git checkout feature/memory-loop
git merge main
```

Create the environment only if needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Then install dependencies using the dependency file that actually exists in the repository, for example:

```bash
pip install -r requirements.txt
```

Do not assume `requirements.txt` exists; inspect the repository first.

### Download only this handoff from GitHub later

After this file has been committed to:

```text
docs/MARK_OS_COMPLETE_PROJECT_HANDOFF.md
```

retrieve it with:

```bash
git fetch origin
git show origin/main:docs/MARK_OS_COMPLETE_PROJECT_HANDOFF.md \
  > docs/MARK_OS_COMPLETE_PROJECT_HANDOFF.md
```

---

## 18. Codex Setup

Codex can be used through:

- the Codex CLI;
- the Codex IDE extension;
- the Codex desktop application;
- Codex web.

For local repository work, the CLI or VS Code extension is recommended.

### Install Codex CLI on macOS

Official installation options include:

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

or:

```bash
brew install --cask codex
```

or:

```bash
npm install -g @openai/codex
```

Start it:

```bash
cd /Users/johnionmiranda/Documents/projects/mark-os
codex
```

Sign in with the ChatGPT account when prompted.

### Initialize project instructions

Inside Codex, use:

```text
/init
```

Review the generated `AGENTS.md` before accepting it. Add the constraints in this handoff.

---

## 19. Immediate Next Task for Codex

Implement **only Step 5.1: Persistent Chat Foundation**.

Do not implement Neo4j, embeddings, LangGraph, Gmail, Calendar, or paid AI calls in the first Codex task.

Expected first deliverable:

- safe migrations for `chat_sessions` and `chat_messages`;
- a chat repository/service layer;
- duplicate protection;
- create/list/get/rename/delete session functions;
- save/edit/delete/retrieve message functions;
- tests;
- no regression to Phase 4;
- no unrestricted SQL or destructive migration.

---

## 20. Codex Working Rules

Codex must:

1. inspect the repository before editing;
2. report the current branch and dirty files;
3. read `app/database.py`, `app/main.py`, current routes, templates, and tests;
4. preserve current coding style;
5. use additive SQLite migrations;
6. create indexes after required columns exist;
7. avoid deleting user data;
8. write tests for migrations and duplicate protection;
9. run the existing test suite;
10. run the app locally;
11. show changed files and a concise summary;
12. stop after Step 5.1 acceptance criteria;
13. never commit, push, deploy, or delete data without explicit approval.

---

## 21. Suggested Commit Sequence

```text
fix(db): stabilize legacy index migrations
feat(chat): add chat session and message schema
feat(chat): add persistent chat repository
feat(chat): add history routes and UI
test(chat): cover persistence and duplicate protection
docs(mark-os): add complete project handoff
```

Keep each commit focused and testable.

---

## 22. Environment Variables Planned

Existing or likely:

```text
MARK_OS_DB_PATH
```

Future Phase 5:

```text
AI_PROVIDER
AI_DEFAULT_MODEL
AI_STRONG_MODEL
AI_API_KEY
EMBEDDING_PROVIDER
EMBEDDING_MODEL
EMBEDDING_DIMENSION
MONTHLY_AI_BUDGET_PHP

NEO4J_URI
NEO4J_USERNAME
NEO4J_PASSWORD
NEO4J_DATABASE
```

Do not put real values in Git.

---

## 23. Open Questions to Resolve During Implementation

- Exact existing route and template conventions.
- Current test framework and coverage.
- Railway volume mount path and current `MARK_OS_DB_PATH`.
- Whether the migration fix is already on `main`.
- Whether the current `memories` table should receive new columns or use companion tables.
- Which AI and embedding provider gives the best verified price at implementation time.
- Whether Neo4j AuraDB Free availability and limits still meet project needs.
- Whether chat messages need soft deletion, hard deletion, or both.
- How user ownership will be added before multi-user support.

Codex should inspect the repository and make evidence-based recommendations rather than guess.

---

## 24. Project Principle

```text
MARK-OS should become more useful because its structured history improves,
not because an AI model is allowed to act without limits.
```

The database remembers.  
The vector store recalls meaning.  
The graph understands relationships.  
LangGraph controls the workflow.  
The AI reasons and communicates.  
The user remains in control.
