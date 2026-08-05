# Phase 6.1J — Relationship Manager and Sales Playbook

Built against:

```text
main commit 0a4c22f
merge: complete phase 6.1 staff research workflow
```

## What this phase adds

- backend role `relationship_manager`;
- UI label **Business Development Collaborator**;
- dedicated landing page `/relationship-manager`;
- private database-backed Markdown playbooks;
- local playbook import command;
- separate `business_development_owner_user_id` lead ownership;
- Relationship Manager CRM visibility and work queues;
- permitted next-action updates;
- Owner-only assignment and reassignment;
- user deactivation cleanup;
- migration, authorization, rendering, and staging-copy tests.

The Relationship Manager still cannot approve research, approve outreach,
change the pipeline, mark Contacted, set pricing or scope, send proposals,
mark Won/Lost, delete leads, manage users, or access private personal areas.

`Contacted` remains locked until Phase 6.2 adds the required activity log.

## 1. Create the feature branch

```bash
cd /Users/johnionmiranda/Documents/projects/mark-os

git switch main
git pull --ff-only origin main
git status

git switch -c feature/relationship-manager-playbook
```

The working tree must be clean before extraction.

## 2. Back up the local database

```bash
python - <<'PY'
from datetime import datetime
from pathlib import Path
import sqlite3

from app import database

source = Path(database.DB_PATH).expanduser().resolve()
backup_dir = Path.home() / "mark-os-backups"
backup_dir.mkdir(parents=True, exist_ok=True)
destination = backup_dir / (
    "mark_os_before_phase_6_1j_"
    + datetime.now().strftime("%Y%m%d_%H%M%S")
    + ".db"
)

if not source.exists():
    print(f"No existing local database: {source}")
else:
    source_db = sqlite3.connect(source)
    backup_db = sqlite3.connect(destination)
    try:
        source_db.backup(backup_db)
    finally:
        backup_db.close()
        source_db.close()

    check = sqlite3.connect(destination)
    try:
        print(f"Backup: {destination}")
        print("Integrity:", check.execute(
            "PRAGMA quick_check"
        ).fetchone()[0])
    finally:
        check.close()
PY
```

## 3. Extract the package

```bash
unzip -o \
  ~/Downloads/PHASE_6_1J_RELATIONSHIP_MANAGER.zip \
  -d .
```

The included internal playbook is placed under:

```text
private_playbooks/JUNMAR_SALES_PLAYBOOK.md
```

That directory is ignored by Git. Do not force-add it.

## 4. Check syntax

```bash
python -m py_compile \
  app/db/playbooks.py \
  app/db/relationship_manager.py \
  app/db/users.py \
  app/routes/relationship_manager.py \
  app/services/playbooks.py \
  app/services/relationship_manager.py \
  tools/import_playbook.py \
  tools/verify_phase_6_1j_release.py \
  tests/test_relationship_manager.py
```

## 5. Run targeted tests

```bash
python -m pytest \
  tests/test_relationship_manager.py \
  tests/test_application.py \
  tests/test_crm_migrations.py \
  tests/test_user_management.py \
  tests/test_sidebar_users_menu.py \
  tests/test_role_permissions.py \
  tests/test_lead_csv_import.py \
  tests/test_lead_work_queues.py \
  tests/test_lead_pipeline_approval.py \
  -q
```

## 6. Run the full suite

```bash
python -m pytest -q
```

Expected Phase 6.1J baseline:

```text
368 passed
```

Do not start the app against a valuable database until the tests pass and a
backup exists.

## 7. Start MARK-OS and create Junmar's account

```bash
uvicorn --env-file .env app.main:app --reload
```

As Mark, open:

```text
http://127.0.0.1:8000/settings/users/new
```

Create:

```text
Username: junmar
Display name: Junmar
Role: Relationship Manager
```

Use a temporary password that is at least ten characters long.

## 8. Import and assign the internal playbook

Stop the development server or open another terminal, then run:

```bash
python tools/import_playbook.py \
  --file private_playbooks/JUNMAR_SALES_PLAYBOOK.md \
  --slug junmar-sales-playbook \
  --assign-username junmar
```

Expected:

```text
Imported playbook: Junmar Sales Playbook
Assigned to: junmar
The Markdown source remains outside Git.
```

The importer may be run again after editing the local Markdown. It updates the
existing database playbook instead of creating duplicates.

## 9. Browser verification

### Mark

- `/settings/users?role=relationship_manager` lists Junmar.
- A lead detail page has a Relationship Manager assignment control.
- Mark can assign or unassign Junmar.
- Mark retains research approval, outreach approval, pipeline, pricing,
  proposal, Won/Lost, deletion, and administration controls.

### Junmar

- Login lands at `/relationship-manager`.
- The assigned sales playbook renders on the front page.
- The front page shows qualification, approved-outreach, due-action,
  waiting-for-Mark, and handoff queues.
- `/crm` shows only leads created by Junmar or assigned to Junmar as Business
  Development Owner.
- A new lead is forced to `New`, assigned operationally to Mark, and records
  Junmar as Business Development Owner.
- Junmar can update the permitted lead's next action and due date.
- Junmar cannot access research edit/review, outreach approval, pipeline,
  Contacted, delete, user settings, quests, history, finance, or family data.

## 10. Verify a copied database before deployment

Find the current database path:

```bash
DB_PATH="$(python - <<'PY'
from pathlib import Path
from app import database
print(Path(database.DB_PATH).expanduser().resolve())
PY
)"

echo "$DB_PATH"
```

Run the Phase 6.1J staging-copy verifier:

```bash
python tools/verify_phase_6_1j_release.py \
  --source-db "$DB_PATH" \
  --output-dir "$HOME/mark-os-release-evidence"
```

Expected:

```text
Phase 6.1J verification PASSED
```

The verifier never writes to the supplied source database. It creates another
SQLite copy, runs the migrations twice, verifies stable data preservation,
runs a Relationship Manager canary, checks XP invariance, and writes a JSON
report.

For a Railway release, run it against a downloaded Railway database backup,
not against the live mounted database.

## 11. Review and commit

Do not use `git add .`.

```bash
git status --short
git diff --check
git diff --stat
```

Stage only the public Phase 6.1J files:

```bash
git add \
  .gitignore \
  PROJECT.md \
  PHASE_6_1J_INSTALL.md \
  app/db/migrations.py \
  app/db/playbooks.py \
  app/db/relationship_manager.py \
  app/db/users.py \
  app/main.py \
  app/routes/client_hunting.py \
  app/routes/relationship_manager.py \
  app/routes/users.py \
  app/services/access_control.py \
  app/services/lead_csv_import.py \
  app/services/lead_research_permissions.py \
  app/services/lead_work_queues.py \
  app/services/leads.py \
  app/services/playbooks.py \
  app/services/relationship_manager.py \
  app/services/team_users.py \
  app/templates/add_leads.html \
  app/templates/base.html \
  app/templates/client_hunting.html \
  app/templates/lead_detail.html \
  app/templates/partials/crm_role_queues.html \
  app/templates/relationship_manager.html \
  app/templates/user_manage.html \
  app/templates/user_new.html \
  app/templates/users.html \
  tests/test_application.py \
  tests/test_crm_migrations.py \
  tests/test_relationship_manager.py \
  tests/test_sidebar_users_menu.py \
  tools/import_playbook.py \
  tools/verify_phase_6_1j_release.py
```

Confirm the private playbook is not staged:

```bash
git status --short
git diff --cached --stat
git diff --cached --check
git check-ignore -v \
  private_playbooks/JUNMAR_SALES_PLAYBOOK.md
```

Commit and push:

```bash
git commit -m \
  "feat(crm): add relationship manager and private sales playbook"

git push -u origin feature/relationship-manager-playbook
```

Merge to `main` only after the full suite, staging-copy verifier, and browser
checks pass.
