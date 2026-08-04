# MARK OS Family Multi-User — M10 Final Release

M10 completes the family workspace architecture started in M7.

## What M10 adds

- Members land on their own private dashboard instead of the temporary setup-only page.
- Every active owner/member receives exactly one profile and game state.
- New member workspaces otherwise begin blank: no copied goals, projects, quests,
  check-ins, memories, history, or chat.
- Members can use the personal OS but cannot access Client Hunting or user management.
- Lead sourcers remain CRM-only.
- Project names become unique per user instead of globally unique.
- Memory keys become unique per user instead of globally unique.
- The navbar and login landing page become family-role aware.
- The release version becomes `0.4.0-family-workspaces`.

## 1. Confirm the branch

From the MARK OS repository:

```bash
git branch --show-current
```

Expected:

```text
feature/family-member-foundation
```

Do not switch branches and do not commit before the final verification.

## 2. Back up the local SQLite database

```bash
python - <<'PY'
from datetime import datetime
from pathlib import Path
import shutil

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

from app import database

source = Path(database.DB_PATH)
if not source.exists():
    print(f"No database exists yet at {source}; no backup required.")
else:
    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = backup_dir / f"{source.stem}_pre_m10_{stamp}{source.suffix}"
    shutil.copy2(source, destination)
    print(f"Backup created: {destination}")
PY
```

## 3. Install the M10 package

Run this from the repository root:

```bash
unzip -o ~/Downloads/MARK_OS_FAMILY_M10_COMPLETE.zip -d .
```

Check the M7-M9 prerequisites:

```bash
python tools/check_m10_prerequisites.py
```

Expected:

```text
M7 member role detected.
M8 ownership schema detected.
M9 request isolation and integrity triggers detected.
M10 prerequisites passed.
```

Apply M10:

```bash
python tools/apply_m10_family_workspace.py
```

Expected:

```text
Installed M10 member workspace initialization.
Enabled member-only personal OS navigation and permissions.
Repaired project and memory uniqueness to be per user.
Updated M7/M8 tests for the completed M10 behavior.
```

## 4. Compile the changed Python files

```bash
python -m py_compile \
  app/main.py \
  app/db/migrations.py \
  app/db/family_workspace.py \
  app/db/goals.py \
  app/db/memory.py \
  app/routes/family.py \
  app/services/access_control.py \
  app/services/team_users.py \
  tests/test_family_workspace_release.py
```

No output means compilation passed.

## 5. Run the family release tests

```bash
python -m pytest \
  tests/test_family_member_foundation.py \
  tests/test_family_data_ownership.py \
  tests/test_family_isolation.py \
  tests/test_family_workspace_release.py \
  -q
```

Then run the complete suite:

```bash
python -m pytest -q
```

The prior suite had 259 tests. M10 adds 6 tests, so the expected result is:

```text
265 passed
```

## 6. Verify the real database

The verifier loads `.env`, initializes the real configured database, checks all
personal ownership, validates M9 triggers, tests role boundaries, and—when an
active member exists—temporarily probes per-user uniqueness inside a rolled-back
savepoint.

```bash
python tools/verify_m10_family_release.py
```

Expected final lines:

```text
Role access boundaries: PASS
PASS: M10 family workspace release verification succeeded.
```

Every personal table must report:

```text
unowned=0, orphan=0
```

### If the verifier says an active owner is required

Check that `.env` contains a real password without printing it:

```bash
python - <<'PY'
import os
from dotenv import load_dotenv

load_dotenv()
print("MARK_OS_USERNAME configured:", bool(os.getenv("MARK_OS_USERNAME")))
print("MARK_OS_PASSWORD configured:", bool(os.getenv("MARK_OS_PASSWORD")))
print("MARK_OS_DISPLAY_NAME configured:", bool(os.getenv("MARK_OS_DISPLAY_NAME")))
PY
```

When `MARK_OS_PASSWORD configured` is `False`, add the missing value to `.env`.
Then initialize again:

```bash
python - <<'PY'
from dotenv import load_dotenv
load_dotenv()

from app.database import init_db
init_db()
print("Database initialized with the configured owner.")
PY
```

Run the M10 verifier again.

## 7. Browser smoke test

Start the application:

```bash
uvicorn --env-file .env app.main:app --reload
```

Verify the owner account:

1. Owner login lands on `/`.
2. Owner sees Today, Quests, Goals, Client Hunting, Life OS, History, and Team.
3. Existing owner records remain present.

Verify a Family Member account:

1. Create one from `/settings/users/new` with account type **Family Member**.
2. Member login lands on `/`.
3. Member sees Today, Quests, Goals, Life OS, and History.
4. Member does not see Client Hunting or Team.
5. The member dashboard starts blank except for level 1 and their profile name.
6. Direct URLs for another user’s quest/check-in return `404`.

Verify a Lead Sourcer account:

1. Lead sourcer login lands on `/crm`.
2. Lead sourcer cannot open `/`, `/quests`, `/goals`, or `/settings/users`.

## 8. Review and commit M7-M10 together

Review all changes first:

```bash
git status --short
git diff --stat
git diff -- app tests README.md
```

Stage the completed application, tests, release documentation, and M10 tools:

```bash
git add app tests README.md M10_INSTALL.md \
  tools/apply_m10_family_workspace.py \
  tools/check_m10_prerequisites.py \
  tools/verify_m10_family_release.py
```

Confirm that secrets and databases are not staged:

```bash
git status --short
```

Do not commit `.env`, SQLite database files, backup files, logs, or generated
`__pycache__` content.

Commit:

```bash
git commit -m "feat: complete family multi-user workspaces"
```

Confirm:

```bash
git status
git log -1 --oneline
```

Do not push or deploy to Railway until the local commit, database backup, full
suite, verifier, and browser smoke test all pass.
