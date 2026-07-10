# MARK OS v0.2.1 — Quest Engine

This patch is designed to be copied over the current MARK OS v0.2 repository.

## What it adds

- clickable quest cards;
- add-your-own quest form;
- visible XP rewards by difficulty;
- Start Quest action;
- progress updates with notes, percent, and time;
- quest completion with result/evidence input;
- one-time XP awards protected by a unique ledger;
- automatic leveling from the current Level 3 baseline;
- hidden level thresholds;
- quest events saved to the timeline;
- Level and tracked XP in the navbar;
- Budget-Safe AI Chat architecture document.

## Safety

The patch does not replace `data/mark_os.db` and does not include a database file.
On startup it safely adds the new columns/tables to the existing Railway database.

## Install on Mac

From your real repo:

```bash
cd ~/Documents/Projects/mark-os
git pull
git status
```

Extract this ZIP in Downloads, then copy the patch:

```bash
cp -R ~/Downloads/mark-os-v0.2.1-quest-engine-patch/app/* app/
cp -R ~/Downloads/mark-os-v0.2.1-quest-engine-patch/tests/* tests/
mkdir -p docs
cp -R ~/Downloads/mark-os-v0.2.1-quest-engine-patch/docs/* docs/
```

Run tests:

```bash
source .venv/bin/activate
pytest -q
```

Expected:

```text
6 passed
```

Run locally:

```bash
uvicorn app.main:app --reload
```

Test:

1. Log in.
2. Open `/quests`.
3. Click a quest.
4. Start it.
5. Add a progress note.
6. Complete it.
7. Confirm XP increases only once.
8. Confirm Level remains at least 3.

Then commit and push:

```bash
git status
git add app tests docs
git commit -m "Add interactive quests, XP, and automatic leveling"
git push
```

Railway will migrate the existing persistent SQLite database at startup.
