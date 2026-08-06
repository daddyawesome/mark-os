# Phase 6.2 — Backup and Disaster Recovery

This phase protects the MARK-OS SQLite database through three independent
layers:

```text
Railway volume snapshots
+ verified SQLite online backups
+ encrypted copies outside Railway
```

A backup is not considered proven until a restore into a new file succeeds.

## Included files

```text
app/services/database_backup.py
tools/backup_database.py
tools/verify_database_backup.py
tools/backup_status.py
tools/restore_database.py
tools/encrypt_backup.py
tools/verify_phase_6_2_release.py
tests/test_database_backup.py
```

## Safety rules

1. Never copy the live SQLite file with plain `cp` while MARK-OS is running.
2. Use SQLite's online backup API through `tools/backup_database.py`.
3. Never restore directly over the configured live database file.
4. Restore to a new filename, verify it, then switch `MARK_OS_DB_PATH` during
   a controlled deployment.
5. Keep at least one encrypted copy outside the Railway volume.
6. Railway volume snapshots and SQLite logical backups are complementary;
   neither replaces the other.

---

## Install and test

From the repository root:

```bash
unzip -o \
  ~/Downloads/PHASE_6_2_BACKUP_RECOVERY.zip \
  -d .
```

Run:

```bash
python -m py_compile \
  app/services/database_backup.py \
  tools/backup_database.py \
  tools/verify_database_backup.py \
  tools/backup_status.py \
  tools/restore_database.py \
  tools/encrypt_backup.py \
  tools/verify_phase_6_2_release.py \
  tests/test_database_backup.py

python -m pytest tests/test_database_backup.py -q
python -m pytest -q
```

---

## Local backup and restore proof

Create a verified backup:

```bash
python tools/backup_database.py
```

Find the newest backup:

```bash
LATEST_BACKUP="$(ls -t data/backups/mark_os_*.sqlite3 | head -1)"
echo "$LATEST_BACKUP"
```

Verify it:

```bash
python tools/verify_database_backup.py \
  --backup "$LATEST_BACKUP"
```

Restore into a new file:

```bash
rm -f data/restore-test.sqlite3

python tools/restore_database.py \
  --backup "$LATEST_BACKUP" \
  --destination data/restore-test.sqlite3
```

Start a temporary instance on another port:

```bash
MARK_OS_DB_PATH="$PWD/data/restore-test.sqlite3" \
uvicorn --env-file .env app.main:app \
  --host 127.0.0.1 \
  --port 8001
```

Open `http://127.0.0.1:8001/health`, then log in and inspect Users and CRM.
Stop the temporary instance with `Ctrl+C`.

Run the automated proof:

```bash
python tools/verify_phase_6_2_release.py \
  --source-db data/mark_os.db \
  --output-dir "$HOME/mark-os-release-evidence" \
  --run-tests
```

Expected:

```text
Phase 6.2 verification PASSED
```

---

## Railway layer 1 — scheduled volume snapshots

In the Railway dashboard:

1. Open the MARK-OS service.
2. Open **Backups** for the attached volume.
3. Create one manual backup now.
4. Lock that first known-good backup.
5. Choose **Edit schedule** and enable an automated daily schedule.
6. Confirm a new scheduled backup appears after the first run.
7. Keep the mount path and database variable aligned:

```text
RAILWAY_VOLUME_MOUNT_PATH=/app/data
MARK_OS_DB_PATH=/app/data/mark_os.db
MARK_OS_BACKUP_DIR=/app/data/backups
```

Railway volume snapshots are the preferred full-volume rollback mechanism.

---

## Railway layer 2 — verified SQLite online backup

Link the CLI to the production service, then open SSH:

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

Copy the exact backup and manifest paths printed by the backup command, then
exit:

```bash
exit
```

Download both files to the Mac:

```bash
mkdir -p "$HOME/mark-os-offsite/plaintext"

railway service files download \
  /app/data/backups/EXACT_BACKUP.sqlite3 \
  "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3"

railway service files download \
  /app/data/backups/EXACT_BACKUP.sqlite3.json \
  "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3.json"
```

Verify the downloaded pair locally:

```bash
python tools/verify_database_backup.py \
  --backup \
  "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3"
```

The manifest is portable: the backup can be moved, but the backup filename
must remain unchanged.

---

## Encrypted offsite copy

Install GnuPG on the Mac once:

```bash
brew install gnupg
```

Symmetric encryption prompts for a passphrase:

```bash
mkdir -p "$HOME/mark-os-offsite/encrypted"

python tools/encrypt_backup.py \
  --backup \
  "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3" \
  --output \
  "$HOME/mark-os-offsite/encrypted/EXACT_BACKUP.sqlite3.gpg"
```

Store the `.gpg`, `.gpg.sha256`, and manifest files in an offsite location
such as an encrypted cloud-drive folder or encrypted external disk. Do not
store the passphrase beside the encrypted file.

Test decryption before deleting the plaintext copy:

```bash
gpg \
  --output "$HOME/mark-os-offsite/restore-check.sqlite3" \
  --decrypt \
  "$HOME/mark-os-offsite/encrypted/EXACT_BACKUP.sqlite3.gpg"

cp \
  "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3.json" \
  "$HOME/mark-os-offsite/restore-check.sqlite3.json"

python tools/verify_database_backup.py \
  --backup "$HOME/mark-os-offsite/restore-check.sqlite3"
```

The decrypted filename must match the filename recorded by the manifest.
When using a different temporary name, copy the manifest and update only the
`backup_filename` field after separately checking the encrypted checksum, or
restore the original filename in a temporary folder.

---

## Production recovery — preferred volume restore

Use this when the entire Railway volume must return to a known snapshot:

1. Stop staff activity and record the incident time.
2. Open the service's **Backups** tab.
3. Select the known-good snapshot by date.
4. Click **Restore**.
5. Review Railway's staged change.
6. Apply the change and wait for redeployment.
7. Verify `/health`, Mark login, Junmar login, Users, CRM, and playbooks.
8. Keep the failed-state evidence until recovery is confirmed.

---

## Production recovery — logical SQLite backup

Use this when restoring one verified SQLite backup rather than the full volume.
Never overwrite `/app/data/mark_os.db` directly.

On the Mac, restore into a new filename:

```bash
python tools/restore_database.py \
  --backup "$HOME/mark-os-offsite/plaintext/EXACT_BACKUP.sqlite3" \
  --destination "$HOME/mark-os-offsite/mark_os_recovered.sqlite3"
```

Upload the recovered file:

```bash
railway service files upload \
  "$HOME/mark-os-offsite/mark_os_recovered.sqlite3" \
  /app/data/restores/mark_os_recovered.sqlite3
```

In Railway Variables, change:

```text
MARK_OS_DB_PATH=/app/data/restores/mark_os_recovered.sqlite3
```

Redeploy, then verify:

```text
/health is HTTP 200
Mark can log in
Junmar can log in
Users are present
CRM leads are present
Playbook assignment is present
```

Rollback from this logical recovery by changing `MARK_OS_DB_PATH` back to the
previous verified database path and redeploying. Do not delete either database
until the recovery decision is final.

---

## Failure visibility

Every logical backup writes one JSON line to:

```text
/app/data/backups/backup_events.jsonl
```

Check freshness and integrity:

```bash
python tools/backup_status.py \
  --directory /app/data/backups \
  --max-age-hours 26
```

A non-zero exit means the backup is missing, stale, corrupt, or has a manifest
mismatch. Review Railway deployment logs and the Backups tab whenever this
command fails.

---

## Phase 6.2 completion evidence

Keep these outside the repository:

```text
full pytest result
Phase 6.2 JSON verification report
Railway scheduled-backup screenshot/date
one downloaded SQLite backup and manifest
one encrypted offsite copy and checksum
one successful decrypt-and-restore test
recovery target path and rollback path
```
