# Phase 6.2 Google Drive Extension

This extension requires the Phase 6.2 backup service:

```text
app/services/database_backup.py
```

It adds:

```text
tools/backup_to_google_drive.py
```

The script creates a verified SQLite online backup in a temporary directory,
uploads the `.sqlite3` file and `.json` checksum manifest to Google Drive,
verifies the transfer by size, applies Google Drive retention, and deletes
the temporary local files.

## Local rclone setup

Install:

```bash
brew install rclone
```

Create a Google Drive remote:

```bash
rclone config
```

Recommended values:

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

Create the folder using rclone so it is available under `drive.file` scope:

```bash
rclone mkdir gdrive:MARK-OS-Backups
rclone lsd gdrive:
```

Test locally:

```bash
python tools/backup_to_google_drive.py \
  --source "$PWD/data/mark_os.db"
```

## Railway variables

Install rclone in the final Railpack image:

```text
RAILPACK_DEPLOY_APT_PACKAGES=rclone
```

Application settings:

```text
MARK_OS_GDRIVE_REMOTE=gdrive
MARK_OS_GDRIVE_FOLDER=MARK-OS-Backups
MARK_OS_GDRIVE_KEEP_LAST=14
MARK_OS_BACKUP_PREFIX=mark_os
```

Transfer the values from `rclone config show gdrive` into Railway variables:

```text
RCLONE_CONFIG_GDRIVE_TYPE=drive
RCLONE_CONFIG_GDRIVE_CLIENT_ID=<client id>
RCLONE_CONFIG_GDRIVE_CLIENT_SECRET=<client secret>
RCLONE_CONFIG_GDRIVE_SCOPE=drive.file
RCLONE_CONFIG_GDRIVE_TOKEN=<complete token JSON>
```

Seal the client secret and token variables in Railway.

Do not commit the rclone configuration or token.

## Railway manual test

After deployment:

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
```

Expected:

```text
MARK-OS Google Drive backup completed.
Remote verification: passed
Temporary Railway files removed: yes
```

Check:

```bash
rclone lsl gdrive:MARK-OS-Backups
```

Exit:

```bash
exit
```

## Important scheduling limitation

The SQLite volume belongs to the MARK-OS web service. A separate cron
service cannot directly read the same mounted volume.

The safe automation pattern is:

```text
Railway cron service
        |
        | authenticated POST
        v
MARK-OS web service backup endpoint
        |
        +-- reads /app/data/mark_os.db
        +-- creates temporary verified backup
        +-- uploads to Google Drive
        +-- deletes temporary files
```

Add that protected endpoint only after the manual Railway upload succeeds.
