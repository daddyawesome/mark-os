# Phase 6.1H–I — Acceptance, Staging, Release, and Rollback

## Starting assumptions

This package must be used only after Phase 6.1G has been installed.

Expected local baseline before adding these files:

```text
Phase 6.1F full suite: 333 passed
Phase 6.1G targeted and full suites: passed
```

The remote GitHub branch must also contain the completed Phase 6.1F and 6.1G
commits before production release verification.

## Phase 6.1H scope

`tests/test_phase_6_1_security_acceptance.py` verifies:

- direct Owner-page access is redirected for the Lead Researcher;
- forged Owner POST requests are rejected before a route executes;
- allowed research routes remain usable;
- unrelated leads remain hidden from the Lead Researcher;
- an unrelated lead cannot be edited or submitted;
- the full Draft → Researching → Review → Changes Requested → Approved
  workflow succeeds;
- Owner outreach approval is required;
- only the Owner can move the pipeline;
- review author and timestamps are recorded;
- workflow audit events are written;
- Member accounts have no CRM authority;
- XP and game state remain unchanged.

## Phase 6.1I scope

`tools/verify_phase_6_1_release.py`:

1. requires an explicit SQLite source path;
2. verifies the source database before copying;
3. creates an online SQLite backup into a staging folder;
4. runs the application migration/validation pipeline only against the copy;
5. checks required Phase 6.1 columns and indexes;
6. validates research and outreach data invariants;
7. runs a complete Lead Researcher → Owner workflow canary;
8. verifies that XP remains unchanged;
9. reruns SQLite integrity and foreign-key checks;
10. optionally runs the full pytest suite;
11. optionally checks a deployed `/health` URL;
12. writes a JSON release-evidence report.

The source database is never migrated or written.

---

# Installation

From the repository root:

```bash
unzip -o \
  ~/Downloads/PHASE_6_1_HI_ACCEPTANCE_RELEASE.zip \
  -d .
```

Added files:

```text
tests/test_phase_6_1_security_acceptance.py
tools/verify_phase_6_1_release.py
PHASE_6_1_HI_RELEASE_RUNBOOK.md
```

No installer and no schema migration are required.

---

# Phase 6.1H tests

Run the new acceptance file:

```bash
python -m pytest \
  tests/test_phase_6_1_security_acceptance.py \
  -q
```

Then run the complete Phase 6.1 test group:

```bash
python -m pytest \
  tests/test_lead_research_migrations.py \
  tests/test_lead_research_permissions.py \
  tests/test_lead_research_workflow.py \
  tests/test_lead_research_review_decisions.py \
  tests/test_lead_pipeline_approval.py \
  tests/test_lead_work_queues.py \
  tests/test_phase_6_1_security_acceptance.py \
  tests/test_role_permissions.py \
  tests/test_lead_ownership.py \
  tests/test_application.py \
  -q
```

Run the full suite:

```bash
python -m pytest -q
```

---

# Commit Phase 6.1H–I files

Stage only these files:

```bash
git add \
  tests/test_phase_6_1_security_acceptance.py \
  tools/verify_phase_6_1_release.py \
  PHASE_6_1_HI_RELEASE_RUNBOOK.md
```

Review:

```bash
git diff --cached --stat
git status --short
```

Commit:

```bash
git commit -m \
  "test(crm): complete phase 6.1 acceptance and release checks"

git push
```

The working tree should be clean before formal 6.1I verification.

---

# Phase 6.1I local staging-copy verification

Use the actual database path shown by MARK-OS, or a downloaded production
snapshot. For a normal local installation this is often:

```text
data/mark_os.db
```

Run:

```bash
python tools/verify_phase_6_1_release.py \
  --source-db data/mark_os.db \
  --run-tests
```

The script creates:

```text
.phase_6_1_release/<UTC timestamp>/mark_os_staging.db
.phase_6_1_release/<UTC timestamp>/phase_6_1_verification.json
```

Expected final output:

```text
Phase 6.1 verification PASSED
```

Do not commit `.phase_6_1_release/`.

## Pre-commit verification

A dirty tree is intentionally rejected by default. For an earlier local
check only:

```bash
python tools/verify_phase_6_1_release.py \
  --source-db data/mark_os.db \
  --allow-dirty
```

Formal release evidence should be produced again after committing, without
`--allow-dirty`.

---

# Verification against a production snapshot

Do not test by modifying the live Railway SQLite file.

1. Create or download a consistent SQLite backup from the Railway volume.
2. Save it outside the repository.
3. Run the verifier against that downloaded snapshot.
4. Inspect the JSON report.
5. Start MARK-OS locally against the generated staging copy.
6. Complete the browser checklist below.
7. Deploy only the verified commit.

Example:

```bash
python tools/verify_phase_6_1_release.py \
  --source-db ~/mark-os-backups/railway-latest.db \
  --run-tests
```

The verifier uses SQLite's online backup API again, so the supplied snapshot
is preserved.

---

# Run MARK-OS against the generated staging copy

Copy the exact staging path printed by the verifier:

```bash
MARK_OS_DB_PATH="/absolute/path/to/mark_os_staging.db" \
uvicorn --env-file .env app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/crm
```

## Owner browser checklist

- Owner queues render.
- Research waiting for review opens the correct lead.
- Changes can be requested with required notes.
- Approved research moves to outreach approval.
- Contacted is blocked before outreach approval.
- Contacted succeeds after outreach approval.
- Proposal is blocked unless the current stage is Meeting.
- Won is blocked unless the current stage is Proposal.
- Lost works from an active stage.
- Soft deletion hides the lead and preserves its quest history.
- No private family or finance behavior changes.

## Lead Researcher browser checklist

- Login lands at `/crm`.
- Only permitted created, assigned, or researched leads appear.
- Draft/researching leads can be edited.
- Requested changes show Owner feedback.
- Submitted work is read-only while waiting for Mark.
- The account cannot open Owner review, settings, edit, delete, pipeline,
  outreach approval, or next-action routes.
- A forged POST to an Owner endpoint returns Forbidden.
- Unrelated staff leads return Not Found or remain absent.

---

# Production deployment sequence

Use the already verified commit.

```bash
git status
git log -1 --oneline
python -m pytest -q
```

Confirm:

```text
working tree clean
full suite passed
production snapshot verification passed
browser staging checklist passed
```

Then deploy through the repository's normal Railway deployment path.

After deployment, verify:

```text
/health returns HTTP 200
Owner can log in
Lead Researcher can log in
/crm renders for both roles
Owner review and outreach controls work
Lead Researcher cannot reach Owner-only controls
```

A deployed health URL may be checked by running:

```bash
python tools/verify_phase_6_1_release.py \
  --source-db ~/mark-os-backups/railway-latest.db \
  --health-url "https://YOUR-MARK-OS-DOMAIN/health"
```

This creates a new staging copy; it does not touch Railway data.

---

# Rollback procedure

## Preferred rollback: application code only

Phase 6.1 database changes are additive. If the deployment has an application
or template problem but the database remains healthy:

1. Stop staff use temporarily.
2. Record the failing deployment commit.
3. Redeploy the last known-good Railway commit.
4. Do not restore the database merely because the code was rolled back.
5. Confirm `/health`, Owner login, and CRM read access.
6. Preserve the failed database and logs for diagnosis.

The older application can normally ignore the additional Phase 6.1 columns.

## Database rollback: only for verified data corruption

Use a database restore only when:

```text
PRAGMA quick_check is not ok
foreign_key_check reports errors
lead records were incorrectly changed
the migration itself damaged production data
```

Before replacing anything:

1. stop the application;
2. create one final copy of the current failed database;
3. record its checksum and deployment commit;
4. confirm the selected backup passes `quick_check`;
5. restore to a new file first;
6. inspect the restored file;
7. replace the live file only after verification.

Never delete the failed database before a verified restore is online.

## Local restore verification

Run the release verifier against the backup intended for restoration:

```bash
python tools/verify_phase_6_1_release.py \
  --source-db /path/to/restore-candidate.db
```

Only a `PASSED` candidate should be considered for restoration.

---

# Phase 6.1 completion evidence

Keep these results:

```text
final commit hash
full pytest result
production-snapshot verification JSON
browser checklist result
deployment URL
post-deploy health result
rollback target commit
```

Phase 6.1 is complete when all acceptance criteria pass and the verified
release is operational for both Mark and the Lead Researcher.
