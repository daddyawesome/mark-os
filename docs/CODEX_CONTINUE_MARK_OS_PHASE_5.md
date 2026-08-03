# Codex Prompt — Continue MARK-OS Phase 5

You are continuing the MARK-OS project in the current Git repository.

Read this first:

```text
docs/MARK_OS_COMPLETE_PROJECT_HANDOFF.md
```

## Mission

Continue MARK-OS safely from the beginning of Phase 5.

MARK-OS is a personal operating system and second brain built with FastAPI, HTMX, Bulma, SQLite, and Railway.

The product is:

```text
AI + database + memory + quests + review + budget + safety
```

The existing Phase 4 Quest Engine and production SQLite data must be preserved.

## Current status

- Phase 4 Quest Engine is completed or substantially implemented.
- Existing SQLite tables include profile, goals, projects, checkins, directions, game_state, game_history, memories, timeline_events, system_meta, tasks, quest_updates, and xp_ledger.
- The app previously failed because indexes were created before migrated columns existed.
- The local database startup is now reported to work.
- Phase 5 feature code has not yet been implemented.
- The intended current branch is `feature/memory-loop`.

## First actions

Before modifying anything, run and report:

```bash
git status
git branch --show-current
git remote -v
git log --oneline --decorate -10
find . -maxdepth 3 -type f | sort
```

Then inspect:

```text
app/database.py
app/main.py
all current route modules
all database/service modules
chat-related templates, if any
tests and dependency files
.gitignore
Railway configuration files
```

Also confirm:

1. whether `app/database.py` contains the migration-order fix;
2. whether the working tree is clean;
3. whether the current branch includes the latest `main`;
4. what test framework is present;
5. how database connections and transactions are currently handled.

Do not guess. Use the repository as the source of truth.

## Implement only Step 5.1

Build the Persistent Chat Foundation.

### Database schema

Add safe, additive migrations for:

```text
chat_sessions
chat_messages
```

Suggested requirements:

### `chat_sessions`

- integer primary key;
- optional user/owner field only if the existing auth model supports it;
- title;
- status or archived flag;
- created timestamp;
- updated timestamp;
- last-message timestamp;
- no destructive migration.

### `chat_messages`

- integer primary key;
- session foreign key;
- role constrained to approved values where practical;
- content;
- optional request/idempotency key for duplicate protection;
- optional edited/deleted metadata;
- created timestamp;
- updated timestamp;
- foreign key with an intentional delete policy.

Do not add an index until every column used by that index is guaranteed to exist.

### Service/repository functions

Implement using the project’s current style:

```text
create_chat_session
get_chat_session
list_chat_sessions
rename_chat_session
delete_or_archive_chat_session
save_chat_message
edit_chat_message
delete_or_soft_delete_chat_message
get_recent_chat_messages
```

### Duplicate protection

Protect against repeated form or network submissions.

Use a deterministic idempotency/request key when possible. Do not treat identical legitimate messages sent at different times as duplicates unless they share the same request key or fall within a clearly documented short retry window.

### History behavior

- Persist complete history in SQLite.
- Normal context retrieval should return only the latest 8–10 active messages.
- Return messages in chronological order.
- Editing and deleting must be explicit and safe.
- Do not expose raw SQL to any future AI tool.

## Tests

Add tests for:

1. a fresh database;
2. a legacy database upgraded without data loss;
3. session creation and retrieval;
4. chronological recent-message retrieval;
5. rename;
6. edit;
7. deletion/archive behavior;
8. duplicate-request protection;
9. foreign-key behavior;
10. app startup after migrations;
11. no regression to existing Quest Engine tables.

Use a temporary database. Never run tests against `data/mark_os.db` or the Railway database.

## Safety constraints

Do not:

- delete or replace the existing SQLite database;
- drop or rename existing tables;
- remove current columns;
- reset XP, level, quests, check-ins, or memories;
- add Neo4j yet;
- add embeddings yet;
- add LangGraph yet;
- add Gmail or Calendar yet;
- add paid AI calls yet;
- hardcode secrets;
- commit `.env`, `.venv`, or database files;
- run `git reset --hard`;
- commit, push, merge, or deploy without my explicit approval.

## Implementation style

- Prefer small, focused files and functions.
- Preserve the repository’s current conventions.
- Use parameterized SQL.
- Use transactions.
- Keep migrations idempotent.
- Provide clear errors.
- Avoid new frameworks when standard library and existing dependencies are sufficient.
- Do not rewrite unrelated code.
- Explain each changed file simply because the project owner is learning.

## Acceptance criteria

Stop when all of the following are true:

- the app starts with a fresh SQLite database;
- the app starts with the current legacy SQLite schema;
- chat sessions persist across restart;
- user and assistant messages persist;
- last 8–10 messages can be retrieved chronologically;
- sessions can be renamed;
- mistaken messages can be edited or safely deleted;
- duplicate retries do not create repeated rows;
- existing quests, XP, levels, check-ins, and memories remain unchanged;
- tests pass;
- no secret or database file is staged.

## Final report

At completion, provide:

1. current branch;
2. changed files;
3. database changes;
4. tests added and results;
5. commands used to run the app;
6. manual verification steps;
7. known limitations;
8. exact recommended commit command and message.

Do not proceed to semantic vectors, Neo4j, LangGraph, AI routing, or the AI Director. Those belong to later Phase 5 steps.
