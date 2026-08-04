# MARK OS Sidebar + Users Menu

This patch:

- moves the top navbar into a responsive left sidebar;
- removes duplicate Team navigation entries;
- renames the administration section to **Users**;
- adds **Family** and **Sourcer** submenus;
- filters `/settings/users` using `?role=member` or
  `?role=lead_sourcer`;
- preserves owner, member, and lead-sourcer access boundaries.

## Install

From the MARK-OS repository root:

```bash
python tools/apply_sidebar_users_menu.py
```

## Test

```bash
python -m pytest tests/test_sidebar_users_menu.py -q
python -m pytest -q
```

## Run locally

```bash
uvicorn --env-file .env app.main:app --reload
```

Check:

- desktop sidebar;
- mobile menu button;
- **Users → Family**;
- **Users → Sourcer**;
- owner-only visibility of the Users menu;
- member personal navigation;
- sourcer CRM-only navigation.

## Commit

```bash
git add \
  app/templates/base.html \
  app/templates/users.html \
  app/routes/users.py \
  tests/test_sidebar_users_menu.py

git commit -m "feat(ui): move navigation to sidebar"
git push origin main
```

The installer stores backups under `.mark_os_backups/`. Do not commit that
folder.
